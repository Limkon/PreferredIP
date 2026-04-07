#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare DNS 更新器 (中国大陆专版)
通过开源社区多源获取优选 IP 并更新 Cloudflare DNS 记录
"""

import json
import traceback
import time
import os
import requests

# ----- API 与 环境变量配置 -----
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_ZONE_ID = os.environ.get("CF_ZONE_ID")
CF_DNS_NAME = os.environ.get("CF_DNS_NAME")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

# 设置需要获取和解析的优选 IP 数量
DISPLAY_IP_COUNT = 2
# 默认超时时间（秒）
DEFAULT_TIMEOUT = 15

# Cloudflare 请求头
CF_HEADERS = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

def get_cn_optimized_ips_from_community(top_n=DISPLAY_IP_COUNT):
    """
    通过多个高频更新的开源社区源获取大陆优选 IP
    """
    ips = []
    print("正在从开源社区获取最新大陆优选 IP...")
    
    # 采用多个稳定、免鉴权的开源社区源，形成容灾机制
    sources = [
        "https://raw.githubusercontent.com/ymyuuu/IPDB/main/bestcf.txt",
        "https://raw.githubusercontent.com/Luminous-B/Cloudflare-IP/main/ip.txt",
        "https://raw.githubusercontent.com/vfarid/cf-ip-scanner/main/ipv4.txt"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    }

    for url in sources:
        print(f"尝试从源拉取: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            if response.status_code == 200:
                lines = response.text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # 强健的解析：处理诸如 "1.1.1.1:443" 或 "1.1.1.1,0.00%丢包" 等复杂格式
                    # 仅提取最前面的 IPv4 地址
                    ip = line.split(',')[0].split(':')[0].strip()
                    
                    # 基础的 IPv4 格式校验
                    if 7 <= len(ip) <= 15 and ip.count('.') == 3:
                        if ip not in ips:
                            ips.append(ip)
                    
                    if len(ips) >= top_n:
                        break
                
                # 如果从当前源成功获取到了足够的 IP，则提前结束轮询
                if ips:
                    print(f"成功从社区源获取 {len(ips)} 个大陆优选 IP。")
                    return ips
            else:
                print(f"该源请求失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"该源获取发生异常: {e}")
            continue

    print("错误: 所有社区源均获取失败。")
    return ips


def get_dns_records(name):
    """获取指定名称的 DNS 记录列表（仅 A 类型）"""
    records = []
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'
    try:
        response = requests.get(url, headers=CF_HEADERS, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            result = response.json().get('result', [])
            for record in result:
                if record.get('name') == name and record.get('type') == 'A':
                    records.append({
                        'id': record['id'],
                        'content': record.get('content', '')
                    })
    except Exception as e:
        print(f'获取 DNS 记录异常: {e}')
        traceback.print_exc()
    return records


def update_dns_record(record_info, name, cf_ip):
    """更新 DNS 记录"""
    record_id = record_info['id']
    current_ip = record_info.get('content', '')

    if current_ip == cf_ip:
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change skip: ---- Time: {current_time} ---- ip：{cf_ip} (已是最新)")
        return f"ip:{cf_ip} 解析 {name} 跳过 (已是最新)"

    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    data = {'type': 'A', 'name': name, 'content': cf_ip}

    try:
        response = requests.put(url, headers=CF_HEADERS, json=data, timeout=DEFAULT_TIMEOUT)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if response.status_code == 200:
            print(f"cf_dns_change success: ---- Time: {current_time} ---- ip：{cf_ip}")
            return f"ip:{cf_ip} 解析 {name} 成功"
        else:
            print(f"cf_dns_change ERROR: ---- Time: {current_time} ---- MESSAGE: {response.text}")
            return f"ip:{cf_ip} 解析 {name} 失败"
    except Exception as e:
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change ERROR: ---- Time: {current_time} ---- MESSAGE: {e}")
        return f"ip:{cf_ip} 解析 {name} 失败"


def push_plus(content):
    """发送 PushPlus 消息推送"""
    if not PUSHPLUS_TOKEN:
        return
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选大陆专版推送",
        "content": content,
        "template": "markdown",
        "channel": "wechat"
    }
    try:
        body = json.dumps(data).encode(encoding='utf-8')
        headers = {'Content-Type': 'application/json'}
        requests.post(url, data=body, headers=headers, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        print(f"消息推送失败: {e}")


def update_local_ip_file(ips):
    """
    将大陆优选结果保存到独立文件 ip_cn.txt 中，避免与国际版冲突
    """
    file_path = "ip_cn.txt"
    try:
        top_ips = ips[:DISPLAY_IP_COUNT]
        ip_list_str = '\n'.join(top_ips)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(ip_list_str)
        print(f"已将大陆优选IP更新至 {file_path}")
    except Exception as e:
        print(f"更新 {file_path} 时发生错误: {e}")


def main():
    """主函数"""
    # 变更：直接从免密社区源抓取纯正 IP
    ip_addresses = get_cn_optimized_ips_from_community(top_n=DISPLAY_IP_COUNT)
    
    if not ip_addresses:
        print("错误: 未能从任何源获取到大陆优选 IP，流程终止。")
        return

    # 生成本地文件（无论有无 Secret 都会生成，保证仓库里有 txt）
    update_local_ip_file(ip_addresses)

    # 如果缺乏环境变量，提前结束，不报异常
    if not all([CF_API_TOKEN, CF_ZONE_ID, CF_DNS_NAME]):
        print("未配置完整的 Secrets，仅将优选结果更新到 ip_cn.txt，不执行 DNS 更新。")
        return

    dns_records = get_dns_records(CF_DNS_NAME)
    if not dns_records:
        print(f"错误: 未找到 {CF_DNS_NAME} 的 DNS 记录")
        return

    if len(ip_addresses) > len(dns_records):
        print(f"警告: IP 数量({len(ip_addresses)})超过 DNS 记录数量({len(dns_records)})，只更新前 {len(dns_records)} 个")
        ip_addresses = ip_addresses[:len(dns_records)]

    push_plus_content = []
    for index, ip_address in enumerate(ip_addresses):
        dns = update_dns_record(dns_records[index], CF_DNS_NAME, ip_address)
        push_plus_content.append(dns)

    if push_plus_content:
        push_plus('\n'.join(push_plus_content))


if __name__ == '__main__':
    main()

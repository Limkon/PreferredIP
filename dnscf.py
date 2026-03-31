#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare DNS 更新器
获取优选 IP 并更新 Cloudflare DNS 记录
"""

import json
import traceback
import time
import os
import csv

import requests

# API 配置
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
CF_ZONE_ID = os.environ.get("CF_ZONE_ID")
CF_DNS_NAME = os.environ.get("CF_DNS_NAME")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

# 请求头
HEADERS = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30


def get_local_speed_test_ips(filepath='result.csv', top_n=20):
    """
    读取本地测速工具生成的 result.csv 文件，获取优选 IP
    """
    ips = []
    if not os.path.exists(filepath):
        print(f"未找到测速结果文件: {filepath}")
        return ips
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)  # 跳过表头 (IP地址,已发送,已接收,丢包率,平均延迟,下载速度)
            for row in reader:
                if row and len(row) > 0:
                    ips.append(row[0].strip())
                    if len(ips) >= top_n:
                        break
    except Exception as e:
        print(f"读取测速结果失败: {e}")
        traceback.print_exc()
        
    return ips


def get_dns_records(name):
    """
    获取指定名称的 DNS 记录列表（仅 A 类型）
    """
    records = []
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records'

    try:
        response = requests.get(url, headers=HEADERS, timeout=DEFAULT_TIMEOUT)
        if response.status_code == 200:
            result = response.json().get('result', [])
            for record in result:
                if record.get('name') == name and record.get('type') == 'A':
                    records.append({
                        'id': record['id'],
                        'content': record.get('content', '')
                    })
        else:
            print(f'获取 DNS 记录失败: {response.text}')
    except Exception as e:
        print(f'获取 DNS 记录异常: {e}')
        traceback.print_exc()

    return records


def update_dns_record(record_info, name, cf_ip):
    """
    更新 DNS 记录
    """
    record_id = record_info['id']
    current_ip = record_info.get('content', '')

    if current_ip == cf_ip:
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change skip: ---- Time: {current_time} ---- ip：{cf_ip} (已是最新)")
        return f"ip:{cf_ip} 解析 {name} 跳过 (已是最新)"

    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record_id}'
    data = {
        'type': 'A',
        'name': name,
        'content': cf_ip
    }

    try:
        response = requests.put(url, headers=HEADERS, json=data, timeout=DEFAULT_TIMEOUT)
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        if response.status_code == 200:
            print(f"cf_dns_change success: ---- Time: {current_time} ---- ip：{cf_ip}")
            return f"ip:{cf_ip} 解析 {name} 成功"
        else:
            print(f"cf_dns_change ERROR: ---- Time: {current_time} ---- MESSAGE: {response.text}")
            return f"ip:{cf_ip} 解析 {name} 失败"
    except Exception as e:
        traceback.print_exc()
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        print(f"cf_dns_change ERROR: ---- Time: {current_time} ---- MESSAGE: {e}")
        return f"ip:{cf_ip} 解析 {name} 失败"


def push_plus(content):
    """
    发送 PushPlus 消息推送
    """
    if not PUSHPLUS_TOKEN:
        print("PUSHPLUS_TOKEN 未设置，跳过消息推送")
        return

    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSCF推送",
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


def update_readme(ips):
    """
    将优选结果更新到 README.md，并清理重复内容
    """
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        print("未找到 README.md 文件，跳过更新。")
        return

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()

        marker_start = ""
        marker_end = ""
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # 截取前 20 个 IP 并使用换行符连接
        top_ips = ips[:20]
        ip_list_str = '\n'.join(top_ips)
        
        replacement = f"{marker_start}\n### 最新优选IP测速结果 (未配置Secrets时展示)\n**更新时间:** {current_time}\n\n```text\n{ip_list_str}\n```\n{marker_end}"

        start_idx = content.find(marker_start)
        end_idx = content.find(marker_end)

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = content[:start_idx] + replacement + content[end_idx + len(marker_end):]
        else:
            fallback_text = "最新优选IP测速结果 (未配置Secrets时展示)"
            fallback_idx = content.find(fallback_text)
            
            if fallback_idx != -1:
                hash_idx = content.rfind("### ", 0, fallback_idx)
                if hash_idx != -1 and (fallback_idx - hash_idx) < 10:
                    content = content[:hash_idx]
                else:
                    content = content[:fallback_idx]
            
            content = content.rstrip() + f"\n\n{replacement}\n"

        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("已将优选IP测速结果更新至 README.md，并已清理重复内容。")
    except Exception as e:
        print(f"更新 README.md 时发生错误: {e}")


def main():
    """主函数"""
    # 直接读取本地测速生成的 result.csv 文件获取前 20 个最优 IP
    ip_addresses = get_local_speed_test_ips(top_n=20)
    
    if not ip_addresses:
        print("错误: 未解析到有效 IP 地址，请检查测速步骤是否正常执行")
        return

    # 检查必要的环境变量
    if not all([CF_API_TOKEN, CF_ZONE_ID, CF_DNS_NAME]):
        print("未配置完整的 Secrets (CF_API_TOKEN, CF_ZONE_ID, CF_DNS_NAME)，将把优选结果更新到 README.md")
        update_readme(ip_addresses)
        return

    # 获取 DNS 记录
    dns_records = get_dns_records(CF_DNS_NAME)
    if not dns_records:
        print(f"错误: 未找到 {CF_DNS_NAME} 的 DNS 记录")
        return

    # 检查记录数量是否足够
    if len(ip_addresses) > len(dns_records):
        print(f"警告: IP 数量({len(ip_addresses)})超过 DNS 记录数量({len(dns_records)})，只更新前 {len(dns_records)} 个")
        ip_addresses = ip_addresses[:len(dns_records)]

    # 更新 DNS 记录
    push_plus_content = []
    for index, ip_address in enumerate(ip_addresses):
        dns = update_dns_record(dns_records[index], CF_DNS_NAME, ip_address)
        push_plus_content.append(dns)

    # 发送推送
    if push_plus_content:
        push_plus('\n'.join(push_plus_content))


if __name__ == '__main__':
    main()

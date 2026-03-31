#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNSPod DNS 更新器
获取优选 IP 并更新 DNSPod DNS 记录
"""

import time
import traceback
import os
import json
import hashlib
import hmac
import csv
from datetime import datetime, timezone
from typing import Dict, Any, List

import requests

# 域名和子域名
DOMAIN = os.environ.get('DOMAIN')
SUB_DOMAIN = os.environ.get('SUB_DOMAIN')

# API 密钥
SECRETID = os.environ.get("SECRETID")
SECRETKEY = os.environ.get("SECRETKEY")

# pushplus_token
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30


class TencentCloudSigner:
    """腾讯云 API 签名类"""

    def __init__(self, secret_id: str, secret_key: str):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.service = "dnspod"
        self.host = "dnspod.tencentcloudapi.com"
        self.region = ""
        self.version = "2021-03-23"

    def _get_signature_key(self, key: str, date_stamp: str, service_name: str) -> bytes:
        k_date = hmac.new(f"TC3{key}".encode('utf-8'), date_stamp.encode('utf-8'), hashlib.sha256).digest()
        k_service = hmac.new(k_date, service_name.encode('utf-8'), hashlib.sha256).digest()
        return hmac.new(k_service, b'tc3_request', hashlib.sha256).digest()

    def sign(self, action: str, payload: Dict[str, Any]) -> Dict[str, str]:
        timestamp = int(time.time())
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

        http_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""

        content_type = "application/json"
        payload_json = json.dumps(payload)
        payload_bytes = payload_json.encode('utf-8')
        hashed_payload = hashlib.sha256(payload_bytes).hexdigest()

        canonical_headers = f"content-type:{content_type}\nhost:{self.host}\nx-tc-action:{action.lower()}\n"
        signed_headers = "content-type;host;x-tc-action"

        canonical_request = (
            f"{http_method}\n"
            f"{canonical_uri}\n"
            f"{canonical_querystring}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{hashed_payload}"
        )

        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{self.service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

        secret_key = self._get_signature_key(self.secret_key, date, self.service)
        signature = hmac.new(secret_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        authorization = (
            f"{algorithm} "
            f"Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        return {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": self.host,
            "X-TC-Action": action,
            "X-TC-Version": self.version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": self.region,
        }


class DnsPodClient:
    """腾讯云 DNSPod API 客户端"""

    def __init__(self, secret_id: str, secret_key: str):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.signer = TencentCloudSigner(secret_id, secret_key)
        self.base_url = "https://dnspod.tencentcloudapi.com"
        self.session = requests.Session()

    def _call_api(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = self.signer.sign(action, payload)
        try:
            response = self.session.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {
                "Response": {
                    "Error": {"Code": "RequestError", "Message": str(e)},
                    "RequestId": ""
                }
            }

    def get_record(self, domain: str, length: int, sub_domain: str, record_type: str) -> Dict[str, Any]:
        payload = {
            "Domain": domain,
            "Subdomain": sub_domain,
            "RecordType": record_type,
            "Limit": length
        }

        resp = self._call_api("DescribeRecordList", payload)
        response = resp.get("Response", {})

        result = {
            "code": 0,
            "data": {"records": [], "domain": {}}
        }

        if "Error" not in response:
            for record in response.get('RecordList', []):
                formatted = {k.lower(): v for k, v in record.items()}
                formatted["id"] = record.get('RecordId')
                result["data"]["records"].append(formatted)

        domain_info = self._call_api("DescribeDomain", {"Domain": domain})
        result["data"]["domain"]["grade"] = domain_info.get("Response", {}).get("DomainInfo", {}).get("Grade", "")
        return result

    def change_record(self, domain: str, record_id: int, sub_domain: str,
                      value: str, record_type: str = "A", line: str = "默认", ttl: int = 600) -> Dict[str, Any]:
        payload = {
            "Domain": domain,
            "SubDomain": sub_domain,
            "RecordType": record_type,
            "RecordLine": line,
            "Value": value,
            "TTL": ttl,
            "RecordId": record_id
        }

        resp = self._call_api("ModifyRecord", payload)
        response = resp.get("Response", {})

        if "Error" in response:
            return {"code": -1, "message": response["Error"].get("Message", "Unknown error")}
        return {"code": 0, "message": "None"}


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


def build_info(client: DnsPodClient) -> List[Dict[str, Any]]:
    def_info = []
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    try:
        ret = client.get_record(DOMAIN, 100, SUB_DOMAIN, 'A')
        records = ret.get("data", {}).get("records", [])

        for record in records:
            if record.get("line") == "默认":
                def_info.append({"recordId": record.get("id"), "value": record.get("value")})

        print(f"build_info success: ---- Time: {current_time} ---- ip：{def_info}")
    except Exception as e:
        traceback.print_exc()
        print(f"build_info ERROR: ---- Time: {current_time} ---- MESSAGE: {e}")

    return def_info


def change_dns(client: DnsPodClient, record_id: int, cf_ip: str) -> str:
    current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    try:
        client.change_record(DOMAIN, record_id, SUB_DOMAIN, cf_ip, "A", "默认", 600)
        print(f"change_dns success: ---- Time: {current_time} ---- ip：{cf_ip}")
        return f"ip:{cf_ip} 解析 {SUB_DOMAIN}.{DOMAIN} 成功"
    except Exception as e:
        traceback.print_exc()
        print(f"change_dns ERROR: ---- Time: {current_time} ---- MESSAGE: {e}")
        return f"ip:{cf_ip} 解析 {SUB_DOMAIN}.{DOMAIN} 失败"


def pushplus(content: str):
    if not PUSHPLUS_TOKEN:
        print("PUSHPLUS_TOKEN 未设置，跳过消息推送")
        return

    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNSPOD推送",
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


def update_readme(ips: List[str]):
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
    if not all([DOMAIN, SUB_DOMAIN, SECRETID, SECRETKEY]):
        print("未配置完整的 Secrets (DOMAIN, SUB_DOMAIN, SECRETID, SECRETKEY)，将把优选结果更新到 README.md")
        update_readme(ip_addresses)
        return

    # 初始化 DNSPod 客户端
    client = DnsPodClient(SECRETID, SECRETKEY)

    # 获取 DNS 记录
    info = build_info(client)
    if not info:
        print(f"错误: 未找到 {SUB_DOMAIN}.{DOMAIN} 的 DNS 记录")
        return

    # 检查记录数量是否足够
    if len(ip_addresses) > len(info):
        print(f"警告: IP 数量({len(ip_addresses)})超过 DNS 记录数量({len(info)})，只更新前 {len(info)} 个")
        ip_addresses = ip_addresses[:len(info)]

    # 更新 DNS 记录
    pushplus_content = []
    for index, ip_address in enumerate(ip_addresses):
        dns = change_dns(client, info[index]["recordId"], ip_address)
        pushplus_content.append(dns)

    # 发送推送
    if pushplus_content:
        pushplus('\n'.join(pushplus_content))


if __name__ == '__main__':
    main()

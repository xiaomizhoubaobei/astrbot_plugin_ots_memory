import base64
import datetime
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional
import aiohttp

logger = logging.getLogger("astrbot")

class OTSMemoryClient:
    """
    轻量级异步 Tablestore Agent Memory REST 客户端
    原生实现阿里云 OTS 签名认证，直连 OpenAPI
    """
    def __init__(
        self,
        endpoint: str,
        instance_name: str,
        access_key_id: str,
        access_key_secret: str,
        region: str = "cn-shanghai",
    ):
        self.endpoint = endpoint.rstrip("/")
        self.instance_name = instance_name
        self.ak_id = access_key_id
        self.ak_secret = access_key_secret
        self.region = region

    def _get_signing_key(self, sign_date: str) -> bytes:
        k_secret = f"aliyun_v4{self.ak_secret}".encode("utf-8")
        h1 = hmac.new(k_secret, sign_date.encode("utf-8"), hashlib.sha256).digest()
        h2 = hmac.new(h1, self.region.encode("utf-8"), hashlib.sha256).digest()
        h3 = hmac.new(h2, b"ots", hashlib.sha256).digest()
        fourth = hmac.new(h3, b"aliyun_v4_request", hashlib.sha256).digest()
        return base64.b64encode(fourth)

    def _build_headers(self, api_name: str, body_bytes: bytes) -> Dict[str, str]:
        now = datetime.datetime.now(datetime.timezone.utc)
        date_str = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        date_only = now.strftime("%Y%m%d")
        
        md5_digest = base64.b64encode(hashlib.md5(body_bytes).digest()).decode("utf-8")
        canonical_uri = f"/{api_name}"

        headers = {
            "x-ots-apiversion": "2015-12-31",
            "x-ots-accesskeyid": self.ak_id,
            "x-ots-instancename": self.instance_name,
            "x-ots-contentmd5": md5_digest,
            "x-ots-date": date_str,
            "x-ots-signdate": date_only,
            "x-ots-signregion": self.region,
        }

        header_items = [
            f"{k.lower()}:{v.strip()}"
            for k, v in headers.items()
            if k.lower().startswith("x-ots-")
        ]
        header_items.sort()
        headers_string = "\n".join(header_items)

        request_string = f"{canonical_uri}\nPOST\n\n{headers_string}\n"
        sign_string = f"{request_string}ots"

        signing_key = self._get_signing_key(date_only)
        signature = base64.b64encode(
            hmac.new(signing_key, sign_string.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        headers["x-ots-signaturev4"] = signature
        headers["Content-Type"] = "application/json"
        headers["User-Agent"] = "@tablestore/agent-storage/python-plugin"
        return headers

    async def _request(self, api_name: str, payload: dict) -> dict:
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = self._build_headers(api_name, body_bytes)
        url = f"{self.endpoint}/{api_name}"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=body_bytes) as resp:
                text = await resp.text()
                if resp.status >= 300:
                    raise RuntimeError(f"OTS API Error [{resp.status}]: {text}")
                return json.loads(text)

    async def search_memories(
        self,
        store_name: str,
        app_id: str,
        tenant_id: str,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        payload = {
            "memoryStoreName": store_name,
            "scope": {
                "appId": app_id,
                "tenantId": tenant_id,
            },
            "query": query,
            "topK": top_k,
            "enableRerank": True,
        }
        if min_score > 0:
            payload["thresholds"] = {"minScore": min_score}

        res = await self._request("SearchMemories", payload)
        # OTS 返回 results 列表
        return res.get("results", [])

    async def add_memories(
        self,
        store_name: str,
        app_id: str,
        tenant_id: str,
        messages: Optional[List[Dict[str, str]]] = None,
        text: Optional[str] = None,
    ) -> dict:
        payload: Dict[str, Any] = {
            "memoryStoreName": store_name,
            "scope": {
                "appId": app_id,
                "tenantId": tenant_id,
                "agentId": "__default__",
                "runId": "__default__",
            },
        }
        if messages:
            payload["messages"] = messages
        if text:
            payload["text"] = text
        return await self._request("AddMemories", payload)

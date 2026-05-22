from abc import ABC, abstractmethod
from typing import List, Dict
import requests


class BaseSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self) -> List[Dict]:
        pass

    def _http_get(self, url: str):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response

    def _http_post(self, url: str, json=None, extra_headers: dict = None):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        if extra_headers:
            headers.update(extra_headers)
        response = requests.post(url, json=json, headers=headers, timeout=30)
        response.raise_for_status()
        return response

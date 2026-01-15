from typing import Optional, List, Dict, Any, Union
import requests
import json
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from checkpoint_sdk.transaction.exceptions import *

class TransactionStatus(str, Enum):
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    PROCESSED = "processed"

class TransactionEncoding(str, Enum):
    BASE64 = "base64"
    BASE58 = "base58"
    JSON_PARSED = "jsonParsed"

@dataclass
class TransactionConfig:
    encoding: TransactionEncoding = TransactionEncoding.JSON_PARSED
    commitment: TransactionStatus = TransactionStatus.CONFIRMED
    max_supported_transaction_version: int = 0
    timeout: int = 30

class TransactionManager:
    def __init__(
        self,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
        headers: Optional[Dict[str, str]] = None,
        config: Optional[TransactionConfig] = None
    ):
        self.rpc_url = rpc_url
        self.headers = headers or {"Content-Type": "application/json"}
        self.config = config or TransactionConfig()
        self.session = requests.Session()

        if self.headers:
            self.session.headers.update(self.headers)

    def _validate_encoding(self, encoding: str) -> None:
        if encoding not in [e.value for e in TransactionEncoding]:
            available = ", ".join([e.value for e in TransactionEncoding])
            raise EncodingNotSupported(
                f"Encoding '{encoding}' not supported. Available: {available}"
            )

    def _make_request(self, method: str, params: List[Any]) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }

        try:
            response = self.session.post(
                self.rpc_url,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            raise TransactionTimeoutError(f"Request timeout exceeded: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise RPCConnectionError(f"RPC connection error: {str(e)}")
        except Exception as e:
            raise RPCConnectionError(f"Unexpected error: {str(e)}")

    def get_transaction(
        self,
        signature: str,
        encoding: Optional[str] = None,
        commitment: Optional[str] = None
    ) -> Dict[str, Any]:
        encoding = encoding or self.config.encoding.value
        commitment = commitment or self.config.commitment.value

        self._validate_encoding(encoding)

        params = [
            signature,
            {
                "encoding": encoding,
                "commitment": commitment,
                "maxSupportedTransactionVersion": self.config.max_supported_transaction_version
            }
        ]

        return self._make_request("getTransaction", params)

    def get_transaction_batch(
        self,
        signatures: List[str],
        encoding: Optional[str] = None,
        commitment: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        encoding = encoding or self.config.encoding.value
        commitment = commitment or self.config.commitment.value

        self._validate_encoding(encoding)

        payload = [
            {
                "jsonrpc": "2.0",
                "id": i,
                "method": "getTransaction",
                "params": [
                    sig,
                    {
                        "encoding": encoding,
                        "commitment": commitment,
                        "maxSupportedTransactionVersion": self.config.max_supported_transaction_version
                    }
                ]
            }
            for i, sig in enumerate(signatures)
        ]

        try:
            response = self.session.post(
                self.rpc_url,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RPCConnectionError(f"Batch request failed: {str(e)}")

    def get_signatures_for_address(
        self,
        address: str,
        limit: int = 1000,
        before: Optional[str] = None,
        until: Optional[str] = None,
        commitment: Optional[str] = None
    ) -> Dict[str, Any]:
        commitment = commitment or self.config.commitment.value

        params = [address]
        options = {"limit": limit}

        if before:
            options["before"] = before
        if until:
            options["until"] = until

        if options:
            params.append(options)

        return self._make_request("getSignaturesForAddress", params)

    def get_transaction_history(
        self,
        address: str,
        limit: int = 10,
        encoding: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        signatures_response = self.get_signatures_for_address(address, limit=limit)

        if "error" in signatures_response:
            return []

        signatures = [sig["signature"] for sig in signatures_response.get("result", [])]

        return self.get_transaction_batch(signatures, encoding=encoding)

    def get_latest_blockhash(
        self,
        commitment: Optional[str] = None
    ) -> Dict[str, Any]:
        commitment = commitment or self.config.commitment.value

        return self._make_request("getLatestBlockhash", [{"commitment": commitment}])

    def confirm_transaction(
        self,
        signature: str,
        commitment: Optional[str] = None,
        timeout: int = 30,
        poll_interval: int = 1
    ) -> bool:
        import time

        commitment = commitment or self.config.commitment.value
        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                result = self.get_transaction(signature, commitment=commitment)

                if result.get("result") is not None:
                    return True

                time.sleep(poll_interval)
            except Exception:
                time.sleep(poll_interval)

        return False

    def parse_transaction_data(
        self,
        transaction_data: Dict[str, Any],
        format_output: bool = False
    ) -> Union[Dict[str, Any], str]:

        if "error" in transaction_data:
            return transaction_data

        result = transaction_data.get("result", {})

        if not format_output:
            return result

        parsed = {
            "signature": result.get("transaction", {}).get("signatures", [""])[0],
            "slot": result.get("slot"),
            "block_time": datetime.fromtimestamp(result.get("blockTime", 0))
                        if result.get("blockTime") else None,
            "fee": result.get("meta", {}).get("fee"),
            "status": "Success" if result.get("meta", {}).get("err") is None else "Failed",
            "instructions_count": len(result.get("transaction", {}).get("message", {}).get("instructions", []))
        }

        return parsed

    def simulate_transaction(
        self,
        transaction_data: str,
        commitment: Optional[str] = None
    ) -> Dict[str, Any]:
        commitment = commitment or self.config.commitment.value

        params = [
            transaction_data,
            {
                "encoding": "base64",
                "commitment": commitment
            }
        ]

        return self._make_request("simulateTransaction", params)

    def get_transaction_cost(
        self,
        transaction_data: str
    ) -> Dict[str, Any]:
        simulation = self.simulate_transaction(transaction_data)

        if "error" in simulation:
            return {"error": simulation["error"]}

        result = simulation.get("result", {})

        return {
            "compute_units_consumed": result.get("unitsConsumed"),
            "fee": result.get("fee"),
            "logs": result.get("logs", [])
        }

    def get_program_accounts(
        self,
        program_id: str,
        encoding: Optional[str] = None,
        commitment: Optional[str] = None
    ) -> Dict[str, Any]:
        encoding = encoding or self.config.encoding.value
        commitment = commitment or self.config.commitment.value

        params = [
            program_id,
            {
                "encoding": encoding,
                "commitment": commitment
            }
        ]

        return self._make_request("getProgramAccounts", params)

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
### --!-- --!-- --!-- better not to use python in Solana high performance production apps --!-- --!-- --!-- ###
import requests
from typing import Optional, Dict, Any, Tuple, List
from checkpoint_sdk.decoder.exceptions import TooManyElements, NoElements
import base64
import struct

class Decoder:
    MAX = 6
    IDLs = []

    def __init__(self, programs):
        programs_count = len(programs)

        if programs_count > self.MAX:
            raise TooManyElements(
                f"Too many programs input! Max programs supported: {self.MAX} | Current input: {programs_count}"
            )
        elif programs_count == 0:
            raise NoElements(
                f"No programs on input! Expected MIN: 1 | MAX: {self.MAX} elements array"
            )

        for program_address in programs:
            idl = self._fetch_idl(program_address)
            self.IDLs.append(idl)
    
    def _find_idl(self, program_address: str):
        for idl in self.IDLs:
            idl_address = idl.get("address")
            if idl_address and idl_address == program_address:
                return idl
    
    def decode(self, base64_str: str, program_address: str):
        """
        Decodes input `Program data:` base64 string by program IDL
        """
        if not isinstance(base64_str, str): raise ValueError(f"Base 64 must be typeof string! Current type: {type(base64_str)} | decode()")
        def normalize_b64(s: str) -> str:
            s = s.strip().split()[-1]
            return s + "=" * (-len(s) % 4)

        idl = self._find_idl(program_address)
        if not idl:
            raise ValueError(f"IDL not found for program: {program_address}")
            
        events = idl.get("events", [])

        b64_clean = normalize_b64(base64_str)
        base64_raw = base64.b64decode(b64_clean)
        discriminator = list(base64_raw[:8])

        for event in events:
            if event.get("discriminator") == discriminator:
                name = event.get("name")
                for _type in idl.get("types", []):
                    if _type.get("name") == name:
                        offset = 8
                        result = {}
                        if "type" in _type and "fields" in _type["type"]:
                            for arg in _type["type"]["fields"]:
                                val, offset = self._read_type(arg["type"], base64_raw, offset, idl)
                                result[arg["name"]] = val
                        return result
        return None

    def _read_primitive(self, t: str, data: bytes, offset: int) -> Tuple[Any, int]:
        if t == "bool":
            return data[offset] == 1, offset + 1

        if t == "u8":
            return data[offset], offset + 1
        if t == "i8":
            return struct.unpack_from("<b", data, offset)[0], offset + 1

        if t == "u16":
            return struct.unpack_from("<H", data, offset)[0], offset + 2
        if t == "i16":
            return struct.unpack_from("<h", data, offset)[0], offset + 2

        if t == "u32":
            return struct.unpack_from("<I", data, offset)[0], offset + 4
        if t == "i32":
            return struct.unpack_from("<i", data, offset)[0], offset + 4

        if t == "u64":
            return struct.unpack_from("<Q", data, offset)[0], offset + 8
        if t == "i64":
            return struct.unpack_from("<q", data, offset)[0], offset + 8

        if t == "u128":
            lo, hi = struct.unpack_from("<QQ", data, offset)
            return (hi << 64) | lo, offset + 16

        if t == "i128":
            lo, hi = struct.unpack_from("<QQ", data, offset)
            val = (hi << 64) | lo
            if hi & (1 << 63):
                val -= 1 << 128
            return val, offset + 16

        if t == "pubkey":
            pubkey_bytes = data[offset:offset+32]
            return self._bytes_to_base58(pubkey_bytes), offset + 32

        raise ValueError(f"Unknown primitive type: {t}")

    def _bytes_to_base58(self, data: bytes) -> str:
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        n = int.from_bytes(data, 'big')
        result = ''
        while n > 0:
            n, remainder = divmod(n, 58)
            result = alphabet[remainder] + result
        
        leading_zeros = 0
        for byte in data:
            if byte == 0:
                leading_zeros += 1
            else:
                break
        return '1' * leading_zeros + result

    def _read_vec(self, inner, data, offset, idl):
        length, offset = self._read_primitive("u32", data, offset)
        items = []

        for _ in range(length):
            val, offset = self._read_type(inner, data, offset, idl)
            items.append(val)

        return items, offset

    def _read_string(self, data, offset):
        length, offset = self._read_primitive("u32", data, offset)
        s = data[offset:offset+length].decode("utf-8")
        return s, offset + length

    def _read_bytes(self, data, offset):
        length, offset = self._read_primitive("u32", data, offset)
        return data[offset:offset+length], offset + length

    def _read_defined(self, name: str, data: bytes, offset: int, idl):
        type_def = None
        for t in idl.get("types", []):
            if t.get("name") == name:
                type_def = t
                break
        
        # if not type_def:
        #     raise ValueError(f"Type definition not found: {name}")

        kind = type_def["type"]["kind"]

        if kind == "struct":
            result = {}
            for field in type_def["type"]["fields"]:
                val, offset = self._read_type(field["type"], data, offset, idl)
                result[field["name"]] = val
            return result, offset

        if kind == "enum":
            discr, offset = self._read_primitive("u8", data, offset)
            if discr >= len(type_def["type"]["variants"]):
                raise ValueError(f"Invalid discriminator: {discr}")
                
            variant = type_def["type"]["variants"][discr]

            if "fields" not in variant:
                return variant["name"], offset

            if isinstance(variant["fields"], list):
                values = []
                for f in variant["fields"]:
                    if isinstance(f, dict):
                        val, offset = self._read_type(f.get("type", f), data, offset, idl)
                    else:
                        val, offset = self._read_type(f, data, offset, idl)
                    values.append(val)
                return {variant["name"]: values}, offset
            else:
                obj = {}
                for f in variant["fields"]:
                    val, offset = self._read_type(f["type"], data, offset, idl)
                    obj[f["name"]] = val
                return {variant["name"]: obj}, offset

    def _read_type(self, t, data: bytes, offset: int, idl):
        if isinstance(t, str):
            if t == "string":
                return self._read_string(data, offset)
            if t == "bytes":
                return self._read_bytes(data, offset)
            return self._read_primitive(t, data, offset)

        if isinstance(t, dict):

            if t.get("kind") == "struct":
                result = {}
                for field in t.get("fields", []):
                    val, offset = self._read_type(field["type"], data, offset, idl)
                    result[field["name"]] = val
                return result, offset

            if t.get("kind") == "enum":
                discr, offset = self._read_primitive("u8", data, offset)
                variant = t["variants"][discr]

                if "fields" not in variant:
                    return variant["name"], offset

                values = {}
                for f in variant.get("fields", []):
                    val, offset = self._read_type(f["type"], data, offset, idl)
                    values[f["name"]] = val

                return {variant["name"]: values}, offset

            if "option" in t:
                flag, offset = self._read_primitive("u8", data, offset)
                if flag == 0:
                    return None, offset
                return self._read_type(t["option"], data, offset, idl)

            if "vec" in t:
                return self._read_vec(t["vec"], data, offset, idl)

            if "array" in t:
                inner, size = t["array"]
                arr = []
                for _ in range(size):
                    val, offset = self._read_type(inner, data, offset, idl)
                    arr.append(val)
                return arr, offset

            if "defined" in t:
                return self._read_defined(t["defined"], data, offset, idl)

        raise ValueError(f"Unknown IDL type: {t}")

    def extract_program_data(self, tx: Dict, program_address: str) -> Optional[str]:
        """
        This function only works in some cases!!!
        Be care using it, not always we can find correct str, so in most cases you need to find base64 data at your own
        """
        params = tx.get("params")
        if not params:
            return None

        results = params.get("result")
        if not results:
            return None

        value = results.get("value")
        if not value:
            return None
        
        logs = value.get("logs")
        if not isinstance(logs, list):
            return None

        for i in range(len(logs) - 1):
            line = logs[i]
            next_line = logs[i + 1]

            if (
                isinstance(line, str)
                and line.startswith("Program data:")
                and isinstance(next_line, str)
                and next_line.startswith(f"Program {program_address} invoke")
            ):
                return line.replace("Program data:", "").strip()

        return None

    def decode_on_demand(self, tx, program_id):
        """
        Automatically extracts first entry `Program data:` of set program address and returns decoded data
        """
        data = self.extract_program_data(tx, program_id)
        return self.decode(data, program_id) if data else None

    def extract_all_program_data(self, tx):
        """
        Extracts all `Program data:` strings from tx, so you can use it to `unsafe` parse all your strings using batch_decode()
        """
        result = []
        params = tx.get("params")
        if not params:
            return None

        results = params.get("result")
        if not results:
            return None

        value = results.get("value")
        if not value:
            return None
        
        logs = value.get("logs")
        if not isinstance(logs, list):
            return None

        for i in range(len(logs) - 1):
            line = logs[i]

            if (
                isinstance(line, str)
                and line.startswith("Program data:")
            ):
                result.append(line.replace("Program data:", "").strip())

        return result

    def batch_decode(self, extract_all_program_data_result: list, program_address: str) -> Optional[List[dict]]:
        results = {}
        for data in extract_all_program_data_result:
            results[data[:10]] = self.decode(data, program_address)
        return results

    def _fetch_idl(self, program_address: str) -> Optional[Dict[str, Any]]:
        url = f"https://api-v2.solscan.io/v2/account/anchor_idl?address={program_address}"

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://solscan.io",
            "Referer": "https://solscan.io/",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                return data.get("data")

            return None

        except Exception as e:
            raise Exception(f"Error fetching IDL for {program_address}: {e}")
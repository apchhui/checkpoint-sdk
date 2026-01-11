import requests
from typing import Optional, Dict, Any
from exceptions import TooManyElements, NoElements

class Decoder:
    MAX = 6

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
            idl = self.fetch_idl(program_address)

    def fetch_idl(self, program_address: str) -> Optional[Dict[str, Any]]:
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


decoder = Decoder([
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
])

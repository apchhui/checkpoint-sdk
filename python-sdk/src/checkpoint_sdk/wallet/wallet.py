from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.system_program import TransferParams, transfer
from solana.rpc.api import Client
from solders.transaction import Transaction
import base58
from typing import Dict, Optional, Union
from checkpoint_sdk.wallet.exceptions import InsufficientBalance

class TransferConfig:
    def __init__(self, fixed_fee_lamports: int = 0, min_amount_lamports: int = 0, 
                 max_amount_lamports: int = 2**63-1, enabled: bool = True):
        self.fixed_fee_lamports = fixed_fee_lamports
        self.min_amount_lamports = min_amount_lamports
        self.max_amount_lamports = max_amount_lamports
        self.enabled = enabled

class WalletManager:
    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com", base_wallet_keypair: Optional[Keypair] = None):
        self.client = Client(rpc_url)
        self.wallets: Dict[str, Keypair] = {}
        self.transfer_config = TransferConfig()
        self.transaction_history = []
        
        if base_wallet_keypair:
            self.base_wallet = base_wallet_keypair
            wallet_id = str(base_wallet_keypair.pubkey())
            self.wallets[wallet_id] = base_wallet_keypair
        else:
            self.base_wallet = Keypair()
            wallet_id = str(self.base_wallet.pubkey())
            self.wallets[wallet_id] = self.base_wallet
    
    def create_wallet(self) -> str:
        new_keypair = Keypair()
        wallet_id = str(new_keypair.pubkey())
        self.wallets[wallet_id] = new_keypair
        return wallet_id
    
    def import_wallet_from_private_key(self, private_key_base58: str) -> str:
        secret_key = base58.b58decode(private_key_base58)
        keypair = Keypair.from_bytes(secret_key)
        wallet_id = str(keypair.pubkey())
        self.wallets[wallet_id] = keypair
        return wallet_id
    
    def get_balance(self, wallet_id: str) -> int:
        if wallet_id not in self.wallets:
            raise ValueError(f"Wallet not found")
        
        pubkey = Pubkey.from_string(wallet_id)
        response = self.client.get_balance(pubkey)
        return response.value
    
    def get_balance_sol(self, wallet_id: str) -> float:
        lamports = self.get_balance(wallet_id)
        return lamports / 1_000_000_000
    
    def set_transfer_config(self, fixed_fee_sol: float = 0.0, min_amount_sol: float = 0.0,
                           max_amount_sol: float = float('inf'), enabled: bool = True):
        fixed_fee_lamports = int(fixed_fee_sol * 1_000_000_000)
        min_amount_lamports = int(min_amount_sol * 1_000_000_000)
        max_amount_lamports = int(max_amount_sol * 1_000_000_000) if max_amount_sol != float('inf') else 2**63-1
        
        self.transfer_config = TransferConfig(fixed_fee_lamports, min_amount_lamports, max_amount_lamports, enabled)
    
    def transfer(self, from_wallet_id: str, to_wallet_id: str, amount_sol: float,
                use_config: bool = False, custom_config: Optional[TransferConfig] = None) -> str:
        if from_wallet_id not in self.wallets:
            raise ValueError(f"Sender wallet not found")
        
        from_keypair = self.wallets[from_wallet_id]
        to_pubkey = Pubkey.from_string(to_wallet_id)
        
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        config = None
        if use_config:
            config = custom_config if custom_config else self.transfer_config
        
        if config and config.enabled:
            if amount_lamports < config.min_amount_lamports:
                raise ValueError(f"Transfer amount too small")
            if amount_lamports > config.max_amount_lamports:
                raise ValueError(f"Transfer amount too large")
        
        fee_lamports = config.fixed_fee_lamports if config and config.enabled else 0
        total_lamports = amount_lamports + fee_lamports
        
        balance = self.get_balance(from_wallet_id)
        if balance < total_lamports:
            raise InsufficientBalance(f"Insufficient SOL balance")
        
        transaction = Transaction()
        transaction.add(
            transfer(
                TransferParams(
                    from_pubkey=from_keypair.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=amount_lamports
                )
            )
        )
        
        if fee_lamports > 0:
            fee_receiver = Pubkey.from_string("11111111111111111111111111111111")
            transaction.add(
                transfer(
                    TransferParams(
                        from_pubkey=from_keypair.pubkey(),
                        to_pubkey=fee_receiver,
                        lamports=fee_lamports
                    )
                )
            )
        
        result = self.client.send_transaction(transaction, from_keypair)
        signature = str(result.value)
        
        transaction_record = {
            'from': from_wallet_id,
            'to': to_wallet_id,
            'amount_sol': amount_sol,
            'amount_lamports': amount_lamports,
            'fee_sol': fee_lamports / 1_000_000_000,
            'fee_lamports': fee_lamports,
            'signature': signature,
            'timestamp': self._get_timestamp()
        }
        self.transaction_history.append(transaction_record)
        
        return signature
    
    def instant_transfer(self, from_wallet_id: str, to_wallet_id: str, amount_sol: float,
                        use_config: bool = False, custom_config: Optional[TransferConfig] = None) -> Dict:
        try:
            signature = self.transfer(from_wallet_id, to_wallet_id, amount_sol, use_config, custom_config)
            
            from_balance = self.get_balance_sol(from_wallet_id)
            to_balance = self.get_balance_sol(to_wallet_id)
            
            result = {
                'status': 'success',
                'signature': signature,
                'explorer_url': f"https://solscan.io/tx/{signature}",
                'from_wallet': from_wallet_id,
                'to_wallet': to_wallet_id,
                'amount_sol': amount_sol,
                'from_balance_sol': from_balance,
                'to_balance_sol': to_balance
            }
            
            return result
            
        except (InsufficientBalance, ValueError) as e:
            result = {
                'status': 'error',
                'message': str(e),
                'from_wallet': from_wallet_id,
                'to_wallet': to_wallet_id
            }
            return result
    
    def airdrop(self, wallet_id: str, amount_sol: float = 1.0) -> str:
        if wallet_id not in self.wallets:
            raise ValueError(f"Wallet not found")
        
        pubkey = Pubkey.from_string(wallet_id)
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        result = self.client.request_airdrop(pubkey, amount_lamports)
        return str(result.value)
    
    def get_recent_blockhash(self) -> str:
        response = self.client.get_recent_blockhash()
        return str(response.value.blockhash)
    
    def estimate_transfer_fee(self, amount_sol: float, use_config: bool = False) -> float:
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        config = None
        if use_config:
            config = self.transfer_config
        
        fee_lamports = config.fixed_fee_lamports if config and config.enabled else 0
        
        response = self.client.get_fee_for_message(self.client.get_recent_blockhash().value.blockhash)
        priority_fee = response.value or 0
        
        total_fee_lamports = fee_lamports + priority_fee
        return total_fee_lamports / 1_000_000_000
    
    def get_wallet_private_key(self, wallet_id: str) -> str:
        if wallet_id not in self.wallets:
            raise ValueError(f"Wallet not found")
        
        keypair = self.wallets[wallet_id]
        return base58.b58encode(bytes(keypair)).decode('utf-8')
    
    def get_wallet_public_key(self, wallet_id: str) -> str:
        if wallet_id not in self.wallets:
            raise ValueError(f"Wallet not found")
        
        return wallet_id
    
    def get_transaction_history(self, wallet_id: Optional[str] = None) -> list:
        if wallet_id:
            return [t for t in self.transaction_history 
                   if t['from'] == wallet_id or t['to'] == wallet_id]
        return self.transaction_history
    
    def _get_timestamp(self) -> str:
        from datetime import datetime
        return datetime.now().isoformat()
    
    def get_network_info(self) -> Dict:
        version = self.client.get_version()
        slot = self.client.get_slot()
        
        return {
            'network': str(self.client._provider.endpoint_uri),
            'solana_version': str(version.value),
            'current_slot': slot.value
        }
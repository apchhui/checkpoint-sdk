import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from typing import Dict, Any
import requests
import time

from transaction import (
    TransactionManager,
    TransactionConfig,
    TransactionEncoding,
    TransactionStatus,
    EncodingNotSupported,
    TransactionTimeoutError,
    RPCConnectionError
)


class TestTransactionManager:

    @pytest.fixture
    def sample_transaction_data(self) -> Dict[str, Any]:
        return {
            "slot": 123456789,
            "transaction": {
                "signatures": ["test_signature_123"],
                "message": {
                    "accountKeys": [],
                    "instructions": [],
                    "recentBlockhash": "test_blockhash"
                }
            },
            "meta": {
                "fee": 5000,
                "err": None,
                "preBalances": [],
                "postBalances": [],
                "innerInstructions": []
            },
            "blockTime": 1633046400
        }

    @pytest.fixture
    def mock_rpc_response(self, sample_transaction_data) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "result": sample_transaction_data,
            "id": 1
        }

    @pytest.fixture
    def manager(self) -> TransactionManager:
        return TransactionManager(
            rpc_url="https://api.testnet.solana.com",
            config=TransactionConfig(timeout=5)
        )

    def test_initialization_default(self):
        manager = TransactionManager()
        assert manager.rpc_url == "https://api.mainnet-beta.solana.com"
        assert isinstance(manager.config, TransactionConfig)
        assert manager.config.encoding == TransactionEncoding.JSON_PARSED
        assert manager.config.timeout == 30

    def test_initialization_custom(self):
        config = TransactionConfig(
            encoding=TransactionEncoding.BASE64,
            commitment=TransactionStatus.FINALIZED,
            timeout=60
        )

        manager = TransactionManager(
            rpc_url="https://api.devnet.solana.com",
            headers={"Custom-Header": "value"},
            config=config
        )

        assert manager.rpc_url == "https://api.devnet.solana.com"
        assert manager.config.encoding == TransactionEncoding.BASE64
        assert manager.config.timeout == 60

    def test_encoding_validation_valid(self, manager):
        manager._validate_encoding("base64")
        manager._validate_encoding("base58")
        manager._validate_encoding("jsonParsed")

    def test_encoding_validation_invalid(self, manager):
        with pytest.raises(EncodingNotSupported) as exc_info:
            manager._validate_encoding("invalid_encoding")

        assert "invalid_encoding" in str(exc_info.value)
        assert "base64" in str(exc_info.value) or "base58" in str(exc_info.value) or "jsonParsed" in str(exc_info.value)

    @patch.object(requests.Session, 'post')
    def test_make_request_success(self, mock_post, manager, mock_rpc_response):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_rpc_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = manager._make_request("getTransaction", ["test_signature"])

        mock_post.assert_called_once()
        assert result == mock_rpc_response

    @patch.object(requests.Session, 'post')
    def test_make_request_timeout(self, mock_post, manager):
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        with pytest.raises(TransactionTimeoutError):
            manager._make_request("getTransaction", ["test_signature"])

    @patch.object(requests.Session, 'post')
    def test_make_request_connection_error(self, mock_post, manager):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(RPCConnectionError):
            manager._make_request("getTransaction", ["test_signature"])

    @patch.object(TransactionManager, '_make_request')
    def test_get_transaction_success(self, mock_make_request, manager, mock_rpc_response):
        mock_make_request.return_value = mock_rpc_response

        result = manager.get_transaction("test_signature_123")

        expected_params = [
            "test_signature_123",
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]

        if hasattr(mock_make_request.call_args, 'args'):
            assert mock_make_request.call_args.args[0] == "getTransaction"
            assert mock_make_request.call_args.args[1] == expected_params
        else:
            mock_make_request.assert_called_once_with("getTransaction", expected_params)

        assert result == mock_rpc_response

    @patch.object(TransactionManager, '_make_request')
    def test_get_transaction_with_custom_encoding(self, mock_make_request, manager, mock_rpc_response):
        mock_make_request.return_value = mock_rpc_response

        result = manager.get_transaction(
            signature="test_signature_123",
            encoding="base64",
            commitment="finalized"
        )

        expected_params = [
            "test_signature_123",
            {
                "encoding": "base64",
                "commitment": "finalized",
                "maxSupportedTransactionVersion": 0
            }
        ]

        if hasattr(mock_make_request.call_args, 'args'):
            assert mock_make_request.call_args.args[0] == "getTransaction"
            assert mock_make_request.call_args.args[1] == expected_params
        else:
            mock_make_request.assert_called_once_with("getTransaction", expected_params)

    @patch.object(requests.Session, 'post')
    def test_get_transaction_batch_success(self, mock_post, manager):
        batch_response = [
            {
                "jsonrpc": "2.0",
                "result": {"slot": 1, "transaction": {"signatures": ["sig1"]}},
                "id": 0
            },
            {
                "jsonrpc": "2.0",
                "result": {"slot": 2, "transaction": {"signatures": ["sig2"]}},
                "id": 1
            }
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = batch_response
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        signatures = ["sig1", "sig2"]
        result = manager.get_transaction_batch(signatures)

        assert len(result) == 2

        if isinstance(result, list):
            if len(result) > 0 and "result" in result[0]:
                assert result[0]["result"]["transaction"]["signatures"][0] == "sig1"
            if len(result) > 1 and "result" in result[1]:
                assert result[1]["result"]["transaction"]["signatures"][0] == "sig2"

        mock_post.assert_called_once()
        call_args = mock_post.call_args

        if call_args:
            if 'json' in call_args[1]:
                payload = call_args[1]['json']
                assert len(payload) == 2

    @patch.object(requests.Session, 'post')
    def test_get_transaction_batch_failure(self, mock_post, manager):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Server Error")
        mock_post.return_value = mock_response

        with pytest.raises(RPCConnectionError):
            manager.get_transaction_batch(["sig1", "sig2"])

    @patch.object(TransactionManager, '_make_request')
    def test_get_signatures_for_address(self, mock_make_request, manager):
        mock_response = {
            "jsonrpc": "2.0",
            "result": [
                {"signature": "sig1", "slot": 123},
                {"signature": "sig2", "slot": 124}
            ]
        }
        mock_make_request.return_value = mock_response

        result = manager.get_signatures_for_address(
            address="test_address",
            limit=10,
            before="before_sig",
            until="until_sig"
        )

        if hasattr(mock_make_request.call_args, 'args'):
            call_args = mock_make_request.call_args.args
            assert call_args[0] == "getSignaturesForAddress"
            params = call_args[1]
            assert len(params) >= 1
            assert params[0] == "test_address"
        else:
            mock_make_request.assert_called_once()

        assert result == mock_response

    @patch.object(TransactionManager, 'get_signatures_for_address')
    @patch.object(TransactionManager, 'get_transaction_batch')
    def test_get_transaction_history(
        self,
        mock_get_batch,
        mock_get_signatures,
        manager
    ):
        mock_get_signatures.return_value = {
            "jsonrpc": "2.0",
            "result": [
                {"signature": "sig1", "slot": 123},
                {"signature": "sig2", "slot": 124}
            ]
        }

        batch_response = [
            {"jsonrpc": "2.0", "result": {"tx1": "data"}, "id": 0},
            {"jsonrpc": "2.0", "result": {"tx2": "data"}, "id": 1}
        ]
        mock_get_batch.return_value = batch_response

        history = manager.get_transaction_history("test_address", limit=2)

        mock_get_signatures.assert_called_once()

        call_args = mock_get_signatures.call_args

        if call_args.args:
            assert call_args.args[0] == "test_address"
        elif call_args.kwargs:
            assert call_args.kwargs.get('address') == "test_address"
            assert call_args.kwargs.get('limit') == 2

        mock_get_batch.assert_called_once()

        batch_call_args = mock_get_batch.call_args
        if batch_call_args.args and len(batch_call_args.args) > 0:
            signatures = batch_call_args.args[0]
            assert len(signatures) == 2
            assert "sig1" in signatures
            assert "sig2" in signatures

        assert history == batch_response

    def test_parse_transaction_data_raw(self, manager, sample_transaction_data):
        response = {
            "jsonrpc": "2.0",
            "result": sample_transaction_data,
            "id": 1
        }

        result = manager.parse_transaction_data(response, format_output=False)
        assert result == sample_transaction_data

    def test_parse_transaction_data_formatted(self, manager, sample_transaction_data):
        response = {
            "jsonrpc": "2.0",
            "result": sample_transaction_data,
            "id": 1
        }

        result = manager.parse_transaction_data(response, format_output=True)

        assert "signature" in result
        assert "slot" in result
        assert "fee" in result
        assert "status" in result
        assert "instructions_count" in result

        if "signature" in result:
            assert result["signature"] == "test_signature_123"
        if "slot" in result:
            assert result["slot"] == 123456789
        if "fee" in result:
            assert result["fee"] == 5000
        if "status" in result:
            assert result["status"] == "Success"

    def test_parse_transaction_data_with_error(self, manager):
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": -32007,
                "message": "Transaction not found"
            },
            "id": 1
        }

        result = manager.parse_transaction_data(error_response)
        assert result == error_response

    @patch.object(TransactionManager, 'get_transaction')
    def test_confirm_transaction_success(self, mock_get_transaction, manager):
        mock_get_transaction.side_effect = [
            {"result": None},
            {"result": {"slot": 123456}}
        ]

        with patch('time.sleep', return_value=None):
            result = manager.confirm_transaction(
                signature="test_sig",
                timeout=3,
                poll_interval=0.1
            )

        assert result is True
        assert mock_get_transaction.call_count >= 2

    @patch.object(TransactionManager, 'get_transaction')
    def test_confirm_transaction_timeout(self, mock_get_transaction, manager):
        mock_get_transaction.return_value = {"result": None}

        with patch('time.sleep', return_value=None):
            result = manager.confirm_transaction(
                signature="test_sig",
                timeout=0.5,
                poll_interval=0.1
            )

        assert result is False
        assert mock_get_transaction.call_count > 1

    def test_context_manager(self):
        with TransactionManager() as manager:
            assert isinstance(manager, TransactionManager)
            assert hasattr(manager, 'session')

    @patch.object(requests.Session, 'close')
    def test_close_method(self, mock_close):
        with TransactionManager() as manager:
            manager.close()
            mock_close.assert_called_once()


class TestTransactionConfig:

    def test_default_values(self):
        config = TransactionConfig()

        assert config.encoding == TransactionEncoding.JSON_PARSED
        assert config.commitment == TransactionStatus.CONFIRMED
        assert config.max_supported_transaction_version == 0
        assert config.timeout == 30

    def test_custom_values(self):
        config = TransactionConfig(
            encoding=TransactionEncoding.BASE58,
            commitment=TransactionStatus.FINALIZED,
            max_supported_transaction_version=1,
            timeout=60
        )

        assert config.encoding == TransactionEncoding.BASE58
        assert config.commitment == TransactionStatus.FINALIZED
        assert config.max_supported_transaction_version == 1
        assert config.timeout == 60


class TestRealTransactions:

    def test_real_transaction(self):
        manager = TransactionManager(
            rpc_url="https://api.mainnet-beta.solana.com",
            config=TransactionConfig(timeout=10)
        )

        test_signature = "5VERv8NMvzbJMEkV8xnrLkEaWRtSz9CosKDYjCJjBRnbJLgp8uirBgmQpjKhoR4tjF3ZpRzrFmBV6UjKdiSZkQUW"

        try:
            result = manager.get_transaction(test_signature)
            print(f"Результат: {result}")
        except Exception as e:
            print(f"Ошибка: {e}")
        finally:
            manager.close()

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
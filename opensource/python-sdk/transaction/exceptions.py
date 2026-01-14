class EncodingNotSupported(Exception):
    pass

class TransactionError(Exception):
    pass

class TransactionTimeoutError(TransactionError):
    pass

class TransactionNotFoundError(TransactionError):
    pass

class RPCConnectionError(TransactionError):
    pass

class InvalidTransactionError(TransactionError):
    pass
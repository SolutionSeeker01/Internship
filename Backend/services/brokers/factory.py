# factory.py - Unified Broker Factory Resolution
'use strict'

from models.broker_account import BrokerAccount
from services.brokers.base import BaseBroker
from services.brokers.zerodha import ZerodhaBroker
from security.encryption import decrypt_value
from exceptions import ValidationException

class BrokerFactory:
    """
    Factory responsible strictly for broker provider resolution.
    Encapsulates database credentials decryption and provider mapping.
    """

    _providers = {
        "ZERODHA": ZerodhaBroker
    }

    @classmethod
    def create(cls, account: BrokerAccount) -> BaseBroker:
        """
        Decrypts credentials from the database BrokerAccount model 
        and instantiates the concrete broker adapter provider.

        :param account: The BrokerAccount ORM model.
        :return: An active instance of BaseBroker contract adapter.
        """
        if not account:
            raise ValidationException("Broker account record is required for factory resolution.")

        if not account.broker:
            raise ValidationException("Broker brand type not specified in account configuration.")

        broker_name = account.broker.strip().upper()
        provider_cls = cls._providers.get(broker_name)

        if not provider_cls:
            raise ValidationException(f"Unsupported broker adapter type: {account.broker}")

        # Decrypt credentials encapsulated within the Factory boundary
        api_key = decrypt_value(account.api_key) if account.api_key else None
        api_secret = decrypt_value(account.api_secret) if account.api_secret else None
        access_token = decrypt_value(account.access_token) if account.access_token else None

        if not api_key:
            raise ValidationException(f"API key credentials missing for broker {account.broker}")

        # Return instantiated adapter matching BaseBroker contract
        return provider_cls(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token
        )

    @classmethod
    def get_broker(cls, broker_name: str, **kwargs) -> BaseBroker:
        """
        Legacy resolver for backward compatibility (where credentials strings are passed directly).
        """
        if not broker_name:
            raise ValueError("Broker name is required")

        broker_upper = broker_name.strip().upper()
        provider_cls = cls._providers.get(broker_upper)

        if not provider_cls:
            raise ValueError(f"Unsupported broker: {broker_name}")

        return provider_cls(**kwargs)

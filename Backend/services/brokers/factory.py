from services.brokers.base import BaseBroker
from services.brokers.zerodha import ZerodhaBroker

class BrokerFactory:
    """
    Factory responsible strictly for broker provider resolution.
    Does not manage credentials, database lookups, or user sessions.
    Maps a broker name to its corresponding concrete BaseBroker implementation.
    """

    _providers = {
        "ZERODHA": ZerodhaBroker
    }

    @classmethod
    def get_broker(cls, broker_name: str, **kwargs) -> BaseBroker:
        """
        Resolves and instantiates the concrete broker provider adapter.

        :param broker_name: The uppercase string name of the broker (e.g., 'ZERODHA').
        :param kwargs: The static credentials required by the broker class constructor.
        :return: An instantiated instance of BaseBroker.
        """
        if not broker_name:
            raise ValueError("Broker name is required")

        broker_upper = broker_name.strip().upper()
        provider_cls = cls._providers.get(broker_upper)

        if not provider_cls:
            raise ValueError(f"Unsupported broker: {broker_name}")

        return provider_cls(**kwargs)

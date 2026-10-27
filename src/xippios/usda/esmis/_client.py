"""The configured ``xippios.core`` client for USDA ESMIS.

One ``AsyncClient`` for the whole package: task functions share its rate limiter and
cache, and the same instance serves the sync facades and the MCP server.
"""

from xippios.core import AsyncClient, ClientConfig, RateLimit

from xippios.usda.esmis._version import __version__

SOURCE = "usda-esmis"
BASE_URL = "https://esmis.nal.usda.gov"
API_KEY_ENV: str | None = None
# A self-imposed pace: upstream documents no limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)

config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
)

# An upstream that reports an hourly or daily quota installs one QuotaPolicy, from
# xippios.core, on config: it reads the quota headers of every answer and never sends
# into a spent quota, waiting within the retry backoff or raising RateLimitError
# (ADR-0015; ADR-0010 decisions 3 and 4). Name only headers that count that quota, never
# a pace (None turns one off); window is the fallback wait, 86400.0 for a daily quota.
# classify, the ClientConfig hook, maps upstream's answer to a spent quota to
# RateLimitError with retry_after. A source without a quota adds nothing.
#
# policy = QuotaPolicy(
#     window=3600.0,
#     limit_header="x-ratelimit-limit",
#     remaining_header="x-ratelimit-remaining",
#     source=SOURCE,
# )
# config = policy.install(config)

client = AsyncClient(config)

__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "RATE_LIMIT",
    "SOURCE",
    "client",
    "config",
]

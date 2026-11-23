"""ORM models. Amounts are always NUMERIC/Decimal, never float."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    """A person who can log in. Identified by the OIDC `sub` claim."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    sub: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    avatar_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    person: Mapped["Person | None"] = relationship(back_populates="user", uselist=False)


class Person(Base):
    """A household member. Assets are assigned to persons; a person may have no login (e.g. a child)."""

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7), default="#15803d")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User | None] = relationship(back_populates="person")


# --- Accounts, holdings and valuations -------------------------------------------------------

MONEY = Numeric(18, 2)
QUANTITY = Numeric(28, 10)
PRICE = Numeric(24, 10)
JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Account(Base):
    """Anything with a value: bank account, portfolio, property, loan, pension, ... (see kinds.py)."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    asset_class: Mapped[str] = mapped_column(String(30))
    institution: Mapped[str] = mapped_column(String(120), default="")
    iban: Mapped[str] = mapped_column(String(34), default="")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    opened_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    settlement_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    bank_login_id: Mapped[int | None] = mapped_column(ForeignKey("bank_logins.id", ondelete="SET NULL"), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owners: Mapped[list["AccountOwner"]] = relationship(back_populates="account", cascade="all, delete-orphan", lazy="selectin")


class AccountOwner(Base):
    """Share of a household member in an account (shares of an account add up to 1)."""

    __tablename__ = "account_owners"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("persons.id", ondelete="RESTRICT"), primary_key=True)
    share: Mapped[Decimal] = mapped_column(Numeric(7, 6))

    account: Mapped[Account] = relationship(back_populates="owners")


class BalanceSnapshot(Base):
    """A known balance of a cash account (or the outstanding debt of a loan) at the end of a day."""

    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("account_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    source: Mapped[str] = mapped_column(String(20), default="manual")


class Transaction(Base):
    """A cash movement on an account (bank booking, contribution, rent, ...)."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    kind: Mapped[str] = mapped_column(String(20), default="other")
    counterparty: Mapped[str] = mapped_column(String(255), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Instrument(Base):
    """A security, coin, precious metal or other unit that can be held in a portfolio."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    wkn: Mapped[str | None] = mapped_column(String(6), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    unit: Mapped[str] = mapped_column(String(10), default="piece")
    price_source: Mapped[str] = mapped_column(String(20), default="manual")
    price_symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    details: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Price(Base):
    """Closing price of an instrument on a day, in the instrument currency."""

    __tablename__ = "prices"
    __table_args__ = (UniqueConstraint("instrument_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    close: Mapped[Decimal] = mapped_column(PRICE)
    source: Mapped[str] = mapped_column(String(20), default="manual")


class Trade(Base):
    """A portfolio transaction: buy, sell, dividend, ... Amounts are in account currency."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=True, index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0"))
    price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    taxes: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    note: Mapped[str] = mapped_column(Text, default="")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Valuation(Base):
    """Value of an asset at a date (property estimate, pension statement, ...)."""

    __tablename__ = "valuations"
    __table_args__ = (UniqueConstraint("account_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(MONEY)
    note: Mapped[str] = mapped_column(Text, default="")


class FxRate(Base):
    """ECB reference rate: 1 EUR = rate units of currency."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("currency", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    date: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class AppState(Base):
    """Small key/value store for job status and similar."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImportBatch(Base):
    """One import run; its rows can be removed together (undo)."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    count: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bank(Base):
    """A bank reachable via FinTS. Shared by the household; personal access data lives in BankLogin."""

    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    blz: Mapped[str] = mapped_column(String(8))
    server_url: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    logins: Mapped[list["BankLogin"]] = relationship(back_populates="bank")


class BankLogin(Base):
    """FinTS access of one user at one bank. The PIN is only stored (encrypted) if the user wants that."""

    __tablename__ = "bank_logins"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id", ondelete="RESTRICT"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(120))
    customer_id: Mapped[str] = mapped_column(String(120), default="")
    tan_mechanism: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tan_mechanism_name: Mapped[str] = mapped_column(String(120), default="")
    tan_medium: Mapped[str | None] = mapped_column(String(120), nullable=True)
    store_pin: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_state: Mapped[str | None] = mapped_column(Text, nullable=True)  # python-fints deconstruct(), base64
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    needs_tan: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bank: Mapped[Bank] = relationship(back_populates="logins", lazy="joined")
    user: Mapped["User | None"] = relationship(lazy="joined")

    # Bank data, read through for the FinTS client.
    @property
    def name(self) -> str:
        return self.bank.name

    @property
    def blz(self) -> str:
        return self.bank.blz

    @property
    def server_url(self) -> str:
        return self.bank.server_url


class OAuthClient(Base):
    """A client registered via OAuth dynamic client registration (e.g. Claude as MCP connector)."""

    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    redirect_uris: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthCode(Base):
    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthToken(Base):
    """Access and refresh tokens; only a hash is stored."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # access | refresh
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

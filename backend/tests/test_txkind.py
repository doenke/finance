from decimal import Decimal as D

from finanzen.services.txkind import guess_kind

DKB = (
    "Abrechnung 30.09.2026 siehe Anlage Abrechnung 30.09.2026 Information zur Abrechnung Kontostand am 30.09.2026 13.360,20 + "
    "Abrechnungszeitraum vom 01.07.2026 bis 30.09.2026 Zinsen für Guthaben 44,18+ 1,0000 v.H. Haben-Zins bis 30.09.2026"
)


def test_guess_kind():
    assert guess_kind("DKB AG", DKB, D("44.18")) == "interest"
    assert guess_kind("Trade Republic", "Zinszahlung Oktober", D("12.10")) == "interest"
    assert guess_kind("", "", D("3.20"), posting_text="Zinsen/Entgelt") == "interest"
    assert guess_kind("Herr Max Muster", "Sparen", D("500")) == "other"
    assert guess_kind("Bank", "Zinsen Darlehen", D("-300")) == "other"  # debits are never interest income
    assert guess_kind("Bausparkasse", "Rate inkl. Zinsen", D("120")) == "other"  # plain "Zinsen" alone is not enough

"""
Interactive CLI dashboard and command loop.

Command reference:
  /status              - show the dashboard again
  /positions           - list open positions
  /risk <1-10>         - change risk level
  /paper               - switch to paper trading (always allowed, instant)
  /live                - switch to live trading (requires typed confirmation)
  /options on|off      - explicitly enable/disable options (still gated by risk level)
  /leverage on|off     - explicitly enable/disable leverage (only levels 9-10)
  /autoexec on|off     - allow LIVE orders to submit without /approve (off by default; use with care)
  find me a trade      - scan the watchlist for a qualifying opportunity
  /approve             - approve and submit the currently pending proposal
  /reject              - discard the currently pending proposal
  /killswitch reset "I UNDERSTAND THE RISK"  - clear a tripped kill switch
  /stop                - immediately disable live trading and refuse new orders
  /help                - show this list
  /quit                - exit
"""
from __future__ import annotations

from trading.analysis.engine import AnalysisEngine
from trading.broker.base import BrokerError
from trading.broker.paper_broker import PaperBroker
from trading.broker.robinhood_agentic_bridge import RobinhoodAgenticBridgeBroker
from trading.broker.robinhood_crypto_broker import RobinhoodCryptoBroker
from trading.config import AppConfig
from trading.data.finnhub_provider import FinnhubProvider
from trading.data.synthetic_provider import SyntheticDataProvider
from trading.execution.kill_switch import RESET_CONFIRMATION_PHRASE, KillSwitch, KillSwitchActive
from trading.execution.order_manager import OrderManager
from trading.logging_setup import get_logger
from trading.models import AssetClass, TradeProposal, TradingMode
from trading.strategy.signal_generator import find_trades

LIVE_CONFIRMATION_PHRASE = "ENABLE LIVE TRADING"


class TradingApp:
    def __init__(self, state_dir: str = "logs", data_provider=None):
        self.state_dir = state_dir
        self.config = AppConfig()
        self.logger = get_logger(state_dir)
        self.kill_switch = KillSwitch(state_dir)

        if data_provider is not None:
            self.data_provider = data_provider
        elif self.config.finnhub_api_key:
            self.data_provider = FinnhubProvider(self.config.finnhub_api_key)
        else:
            print("NOTE: FINNHUB_API_KEY not set - using synthetic offline data for this session. "
                  "Set FINNHUB_API_KEY for real market data before making real decisions.")
            self.data_provider = SyntheticDataProvider()

        self.analysis_engine = AnalysisEngine(self.data_provider, stop_atr_multiple=self.config.risk_profile().stop_loss_atr_multiple)

        self.paper_broker = PaperBroker(self.data_provider, state_dir)
        self.order_manager = OrderManager(self.paper_broker, self.kill_switch, self.logger, state_dir)

        self._crypto_broker = None  # constructed lazily; needs credentials
        self._equity_bridge_broker = RobinhoodAgenticBridgeBroker(state_dir)

        self.pending_proposal: TradeProposal | None = None
        self.running = True

    # -- broker routing --------------------------------------------------------------
    def broker_for(self, asset_class: AssetClass):
        if self.config.mode == TradingMode.PAPER:
            return self.paper_broker
        if asset_class == AssetClass.CRYPTO:
            if self._crypto_broker is None:
                self._crypto_broker = RobinhoodCryptoBroker(
                    self.config.crypto_api_key, self.config.crypto_private_key_b64, self.state_dir
                )
            return self._crypto_broker
        return self._equity_bridge_broker

    # -- dashboard ---------------------------------------------------------------------
    def print_dashboard(self) -> None:
        print("=" * 60)
        if self.kill_switch.is_tripped():
            print(f"** KILL SWITCH ACTIVE ** reason: {self.kill_switch.state.reason}")
        if self.config.mode == TradingMode.PAPER:
            account = self.paper_broker.get_account()
            store = self.paper_broker.store.state
            today_pl = account.portfolio_value - store.daily_start_value
            total_pl = account.portfolio_value - store.inception_cash
            print(f"Trading Mode: PAPER")
            print(f"Risk Level: {self.config.risk_level}/10 ({self.config.risk_profile().label})")
            print(f"Portfolio: ${account.portfolio_value:,.2f}")
            print(f"Cash: ${account.cash:,.2f}")
            print(f"Today's P/L: {today_pl:+,.2f}")
            print(f"Total P/L: {total_pl:+,.2f}")
            print(f"Open Positions: {len(account.positions)}")
        else:
            print("Trading Mode: LIVE")
            print(f"Risk Level: {self.config.risk_level}/10 ({self.config.risk_profile().label})")
            try:
                account = self._equity_bridge_broker.get_account()
                print(f"Portfolio (equities/options, via agent snapshot): ${account.portfolio_value:,.2f}")
                print(f"Cash: ${account.cash:,.2f}")
                print(f"Open Positions: {len(account.positions)}")
            except BrokerError as e:
                print(f"Portfolio: UNAVAILABLE - {e}")
        print(f"Daily Loss Limit: {self.config.limits.max_daily_loss_percent:.0%}")
        print(f"Options enabled: {self.config.allow_options} | Leverage enabled: {self.config.allow_leverage}")
        print("=" * 60)

    # -- commands ------------------------------------------------------------------------
    def handle(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        lower = line.lower()

        if lower in ("find me a trade", "find a trade", "/find"):
            self._cmd_find_trade()
        elif lower == "/status":
            self.print_dashboard()
        elif lower == "/positions":
            self._cmd_positions()
        elif lower.startswith("/risk"):
            self._cmd_risk(line)
        elif lower == "/paper":
            self._cmd_paper()
        elif lower == "/live":
            self._cmd_live()
        elif lower.startswith("/options"):
            self._cmd_toggle("allow_options", line)
        elif lower.startswith("/leverage"):
            self._cmd_toggle("allow_leverage", line)
        elif lower.startswith("/autoexec"):
            self._cmd_toggle("auto_execute_live", line)
        elif lower == "/approve":
            self._cmd_approve()
        elif lower == "/reject":
            self._cmd_reject()
        elif lower.startswith("/killswitch"):
            self._cmd_killswitch(line)
        elif lower == "/stop":
            self._cmd_stop()
        elif lower in ("/help", "help", "?"):
            print(__doc__)
        elif lower in ("/quit", "/exit"):
            self.running = False
        else:
            print("Unrecognized command. Type /help for the command list.")

    def _cmd_positions(self) -> None:
        try:
            account = self.paper_broker.get_account() if self.config.mode == TradingMode.PAPER else self._equity_bridge_broker.get_account()
        except BrokerError as e:
            print(f"Could not fetch positions: {e}")
            return
        if not account.positions:
            print("No open positions.")
            return
        for p in account.positions:
            print(f"  {p.symbol:<6} qty={p.quantity:g} avg_price=${p.avg_price:,.2f} cost_basis=${p.cost_basis:,.2f}")

    def _cmd_risk(self, line: str) -> None:
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdigit():
            print("Usage: /risk <1-10>")
            return
        level = int(parts[1])
        if not 1 <= level <= 10:
            print("Risk level must be between 1 and 10.")
            return
        self.config.risk_level = level
        self.analysis_engine.stop_atr_multiple = self.config.risk_profile().stop_loss_atr_multiple
        self.logger.event("risk_level_changed", new_level=level)
        print(f"Risk level set to {level}/10 ({self.config.risk_profile().label}).")

    def _cmd_paper(self) -> None:
        self.config.mode = TradingMode.PAPER
        self.logger.event("mode_changed", mode="PAPER")
        print("Switched to PAPER trading.")

    def _cmd_live(self) -> None:
        print("You are about to enable LIVE trading with real money.")
        print(f'Type exactly "{LIVE_CONFIRMATION_PHRASE}" to confirm, or anything else to cancel:')
        confirmation = input("> ").strip()
        if confirmation != LIVE_CONFIRMATION_PHRASE:
            print("Live trading NOT enabled.")
            return
        if self.kill_switch.is_tripped():
            print(f"Cannot enable live trading: kill switch is active ({self.kill_switch.state.reason}).")
            return
        self.config.mode = TradingMode.LIVE
        self.logger.event("mode_changed", mode="LIVE")
        print("LIVE trading enabled. Every order still requires /approve unless /autoexec is on.")

    def _cmd_toggle(self, attr: str, line: str) -> None:
        parts = line.split()
        if len(parts) != 2 or parts[1].lower() not in ("on", "off"):
            print(f"Usage: {parts[0]} on|off")
            return
        value = parts[1].lower() == "on"
        if attr == "allow_leverage" and value and self.config.risk_level < 9:
            print("Leverage can only be enabled at risk level 9 or 10.")
            return
        if attr == "auto_execute_live" and value:
            print("WARNING: auto-execute will submit LIVE orders without asking for /approve.")
        setattr(self.config, attr, value)
        self.logger.event("config_toggled", setting=attr, value=value)
        print(f"{attr} = {value}")

    def _cmd_find_trade(self) -> None:
        try:
            account = self.paper_broker.get_account() if self.config.mode == TradingMode.PAPER else self._equity_bridge_broker.get_account()
        except BrokerError as e:
            print(f"Cannot scan for trades: account state unavailable - {e}")
            return
        daily_start = (
            self.paper_broker.store.state.daily_start_value
            if self.config.mode == TradingMode.PAPER
            else account.portfolio_value
        )
        proposals, candidates = find_trades(
            account=account,
            daily_start_value=daily_start,
            config=self.config,
            data_provider=self.data_provider,
            analysis_engine=self.analysis_engine,
        )
        if not proposals:
            print("NO TRADE — No opportunity currently meets the required risk/reward criteria.")
            self.logger.event("no_trade_found", scanned=len(candidates))
            return
        best = proposals[0]
        self.pending_proposal = best
        self.logger.event("trade_proposed", proposal_id=best.id, symbol=best.symbol)
        print(self._format_proposal(best))
        if self.config.mode == TradingMode.LIVE and not self.config.auto_execute_live:
            print("\nTRADE PROPOSED — WAITING FOR APPROVAL")
        print("\nUse /approve to submit this trade, or /reject to discard it.")
        if self.config.auto_execute_live and self.config.mode == TradingMode.LIVE:
            self._submit_pending()

    def _format_proposal(self, p: TradeProposal) -> str:
        lines = [
            f"{p.symbol}",
            f"Signal: {p.side.value.upper()}",
            f"Shares: {p.quantity:g}",
            f"Current Price: ${p.entry_price:,.2f}",
            f"Estimated Order Value: ${p.estimated_order_value:,.2f}",
            f"Portfolio % After Trade: {p.portfolio_pct_after:.1%}",
            f"Entry: ${p.entry_price:,.2f}",
            f"Stop: ${p.stop_loss:,.2f}",
            f"Maximum Loss: ${p.max_dollar_loss:,.2f} ({p.risk_pct_of_portfolio:.2%} of portfolio)",
            f"Confidence: {p.confidence}/100" if p.confidence is not None else "Confidence: n/a",
            f"Risk Level: {p.risk_level}",
            f"Estimated Upside: ${p.upside_estimate:,.2f}" if p.upside_estimate is not None else "",
            f"Estimated Downside: ${p.downside_estimate:,.2f}" if p.downside_estimate is not None else "",
            f"Reason: {p.reason}",
            f"Major Risks: {', '.join(p.major_risks) if p.major_risks else 'none flagged'}",
        ]
        return "\n".join(l for l in lines if l)

    def _cmd_approve(self) -> None:
        if self.pending_proposal is None:
            print("No trade is pending approval.")
            return
        self.logger.event("trade_approved", proposal_id=self.pending_proposal.id, symbol=self.pending_proposal.symbol)
        self._submit_pending()

    def _submit_pending(self) -> None:
        proposal = self.pending_proposal
        if proposal is None:
            return
        broker = self.broker_for(proposal.asset_class)
        try:
            record = self.order_manager.submit(proposal, self.config.mode)
        except KillSwitchActive as e:
            print(f"BLOCKED: {e}")
            return
        except BrokerError as e:
            print(f"Order not placed: {e}")
            return
        finally:
            self.pending_proposal = None
        print(f"Order status: {record.status.value}")
        if record.notes:
            print(record.notes)

    def _cmd_reject(self) -> None:
        if self.pending_proposal is None:
            print("No trade is pending approval.")
            return
        self.logger.event("trade_rejected", proposal_id=self.pending_proposal.id, symbol=self.pending_proposal.symbol)
        print(f"Rejected proposed trade for {self.pending_proposal.symbol}.")
        self.pending_proposal = None

    def _cmd_killswitch(self, line: str) -> None:
        parts = line.split(maxsplit=2)
        if len(parts) == 1:
            status = "ACTIVE" if self.kill_switch.is_tripped() else "clear"
            print(f"Kill switch: {status}" + (f" ({self.kill_switch.state.reason})" if self.kill_switch.is_tripped() else ""))
            return
        if len(parts) == 3 and parts[1].lower() == "reset" and parts[2].strip('"') == RESET_CONFIRMATION_PHRASE:
            ok = self.kill_switch.reset(RESET_CONFIRMATION_PHRASE, logger=self.logger)
            print("Kill switch reset." if ok else "Reset failed.")
            return
        print(f'Usage: /killswitch reset "{RESET_CONFIRMATION_PHRASE}"')

    def _cmd_stop(self) -> None:
        self.config.mode = TradingMode.PAPER
        self.config.auto_execute_live = False
        self.kill_switch.trip("manual /stop command", logger=self.logger)
        print("Live trading disabled and kill switch activated. No new orders will be placed.")


def run() -> None:
    app = TradingApp()
    app.print_dashboard()
    print("\nType 'find me a trade' or /help for commands.")
    while app.running:
        try:
            line = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            break
        app.handle(line)


if __name__ == "__main__":
    run()

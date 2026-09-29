# TradeBot — بوت تداول عملات رقمية

بوت تداول مكتوب بلغة Python، مقسَّم إلى وحدات مستقلة. يدعم **الاختبار التاريخي (Backtest)** و**التداول الورقي (Paper)** و**التداول الحقيقي (Live)**
على أي منصة تدعمها مكتبة [ccxt](https://github.com/ccxt/ccxt) (Binance, Bybit, OKX, Kraken, KuCoin …).

> ⚠️ **تحذير:** التداول ينطوي على مخاطر عالية وقد تخسر رأس مالك. الاستراتيجيات المرفقة أمثلة تعليمية وليست نصيحة مالية.
> ابدأ دائماً بـ backtest، ثم paper، ثم testnet (`sandbox: true`)، وبعدها فقط بمبلغ صغير حقيقي.

## المميزات

| الوحدة | الوصف |
|---|---|
| `strategies/` | 3 استراتيجيات: `ema_cross` (تتبع الاتجاه + فلتر ADX)، `rsi_reversion` (الارتداد إلى المتوسط + Bollinger)، `macd_trend`، مع واجهة سهلة لإضافة استراتيجيتك |
| `indicators.py` | SMA, EMA, RSI, MACD, ATR, Bollinger, ADX بدون الحاجة إلى TA-Lib |
| `risk.py` | حجم الصفقة حسب نسبة المخاطرة، وقف خسارة وجني أرباح يعتمدان على ATR، وقف متحرك، حد خسارة يومي، ومفتاح إيقاف عند تجاوز أقصى تراجع |
| `backtest.py` | محاكاة شمعة بشمعة دون النظر إلى بيانات مستقبلية، مع حساب العمولات والانزلاق السعري، وفجوات السعر عند وقف الخسارة |
| `metrics.py` | العائد، CAGR، Sharpe، Sortino، Calmar، أقصى تراجع، نسبة الربح، Profit Factor |
| `engine.py` | حلقة التداول الحي: تعمل على الشموع المغلقة فقط، وتحفظ الحالة على القرص لاستئناف الصفقات بعد إعادة التشغيل، وتعيد المحاولة عند أخطاء الشبكة، وتتوقف بأمان |
| `exchange.py` | منصة حقيقية عبر ccxt أو منصة ورقية تستخدم أسعاراً حية وتحاكي التنفيذ محلياً |
| `notifier.py` | إشعارات Telegram للصفقات والأخطاء |
| `report.py` | تقرير HTML تفاعلي فيه الشموع ونقاط الدخول والخروج ومنحنى رأس المال |
| `cli optimize` | بحث شبكي عن أفضل المعاملات، مع اختبار على بيانات لم تُستخدم في التحسين (out-of-sample) |

## التثبيت

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp config.example.yaml config.yaml
cp .env.example .env        # ضع مفاتيح API هنا فقط
```

## الاستخدام

```bash
# 1) اختبار تاريخي على بيانات حقيقية (تُحمَّل من المنصة) مع تقرير HTML
python -m tradebot backtest -c config.yaml --plot reports/report.html --trades reports/trades.csv

# تجربة بدون إنترنت على بيانات مولَّدة
python -m tradebot backtest --synthetic --strategy macd_trend

# 2) تحسين المعاملات (70% للتدريب، و30% للتحقق خارج العينة)
python -m tradebot optimize -c config.yaml --grid fast=8,12,16 slow=21,26,34

# 3) حفظ البيانات التاريخية في ملف CSV لاستخدامها لاحقاً (backtest.data_file)
python -m tradebot download -c config.yaml --out data/btc_1h.csv

# 4) تداول ورقي: أسعار حقيقية وأموال وهمية
python -m tradebot paper -c config.yaml

# 5) تداول حقيقي: على testnet أولاً (sandbox: true)
python -m tradebot live -c config.yaml

# حالة البوت: الصفقة المفتوحة، والأرباح والخسائر المحققة
python -m tradebot status -c config.yaml
```

يمكن تغيير الزوج أو الإطار الزمني أو الاستراتيجية من سطر الأوامر: `--symbol ETH/USDT --timeframe 4h --strategy rsi_reversion`.

### التشغيل بـ Docker

```bash
docker compose up -d --build
docker compose logs -f
```

### إشعارات Telegram

1. أنشئ بوتاً عبر [@BotFather](https://t.me/BotFather) واحصل على الـ token.
2. ضع `TELEGRAM_TOKEN` و`TELEGRAM_CHAT_ID` في ملف `.env`.
3. اجعل `telegram.enabled: true` في ملف `config.yaml`.

## كيف يعمل

```
كل poll_seconds:
  1. جلب السعر الحالي ← إذا وصل إلى وقف الخسارة أو جني الأرباح: بيع فوري
  2. تحديث رأس المال، والحد اليومي، وأقصى تراجع
  3. عند إغلاق شمعة جديدة: حساب الإشارة
       SELL + صفقة مفتوحة  ← بيع
       BUY  + لا صفقة      ← حساب الحجم (المخاطرة ÷ مسافة الوقف) ← شراء
       غير ذلك             ← تحريك الوقف المتحرك
  4. حفظ الحالة في data/state.json
```

**حجم الصفقة:** `الكمية = رأس المال × risk_per_trade ÷ (ATR × stop_atr_mult)`، بشرط ألا تتجاوز قيمة الصفقة `max_position_pct` من رأس المال.
بالإعدادات الافتراضية، كل صفقة تخسر حوالي 1% فقط من رأس المال إذا ضُرب الوقف.

**مفتاح الإيقاف:** إذا تراجع رأس المال بنسبة `max_drawdown` عن أعلى قيمة وصل إليها، يتوقف البوت عن فتح صفقات جديدة.
للاستئناف، راجع الأداء ثم احذف `halted` من ملف الحالة.

## إضافة استراتيجية جديدة

```python
# tradebot/strategies/my_strategy.py
from .. import indicators as ind
from .base import BUY, SELL, HOLD, Strategy
import pandas as pd

class MyStrategy(Strategy):
    name = "my_strategy"
    defaults = {"period": 50}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ma = ind.sma(df["close"], self.params["period"])
        s = pd.Series(HOLD, index=df.index)
        s[df["close"] > ma] = BUY
        s[df["close"] < ma] = SELL
        return s
```

بعدها أضفها إلى `STRATEGIES` في `tradebot/strategies/__init__.py`.
**قاعدة مهمة:** لا تستخدم بيانات مستقبلية مثل `shift(-1)`. الاختبار `test_strategies_have_no_lookahead` يتحقق من ذلك تلقائياً.

## الاختبارات

```bash
pytest -q
```

## ملاحظات وحدود

- بعض المنصات تحجب الطلبات من دول معيّنة أو من خوادم سحابية. Binance مثلاً ترد بالرمز 451، وقد ترد Bybit بالرمز 403. في هذه الحالة غيّر `exchange.name` إلى `okx` أو `kraken`، أو شغّل البوت من منطقة مسموح بها.
- البوت يستخدم متغيرات البيئة `HTTPS_PROXY` و`REQUESTS_CA_BUNDLE` إن وُجدت، لذا يعمل خلف بروكسي الشركات.

- البوت يتداول في السوق الفوري (spot) وبصفقات شراء فقط، بدون رافعة مالية ولا بيع على المكشوف.
- يراقب البوت وقف الخسارة وجني الأرباح بنفسه عبر السعر الحالي، ولا يضع أوامر وقف على المنصة. لذلك يجب أن يبقى البوت يعمل باستمرار (Docker مع `restart: unless-stopped`).
- في وضع live، يُحسب رأس المال من رصيد عملة التسعير (USDT) مضافاً إليه قيمة صفقة البوت فقط، وأي عملات أخرى في الحساب لا تُحتسب.
- أداء الـ backtest لا يضمن الأداء المستقبلي. احذر من الإفراط في التحسين (overfitting)، واعتمد دائماً على نتائج البيانات خارج العينة.

---

## English summary

Modular Python crypto trading bot built on ccxt: backtesting (no look-ahead, fees, slippage, gap-aware stops),
paper trading on live prices, live trading, ATR-based risk sizing, trailing stops, daily-loss and max-drawdown
circuit breakers, persisted state, Telegram alerts, HTML reports and a grid-search optimizer with out-of-sample validation.
Start with `cp config.example.yaml config.yaml && python -m tradebot backtest --synthetic`.

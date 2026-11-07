---
name: 聪明钱概念信号引擎
description: Smart Money Concepts（ICT）信号引擎，借助 smartmoneyconcepts 库实现 BOS、ChoCH、FVG 与订单块等机构交易流派分析。
category: strategy
---
# Smart Money Concepts

## Purpose

The modern institutional trading school (ICT / Inner Circle Trader), built around the core idea of tracking the behavior of "smart money" (institutional capital):

| Concept | English | Meaning |
|------|------|------|
| Break of structure | BOS (Break of Structure) | Trend continuation signal |
| Change of character | ChoCH (Change of Character) | Trend reversal signal |
| Fair value gap | FVG (Fair Value Gap) | Price refill target |
| Order blocks | Order Blocks | Institutional order concentration zones |
| Liquidity | Liquidity | Stop-hunt target zones |

## Signal Logic

Direction from ChoCH + confirmation from BOS + filtering by FVG:
- **Long**: bullish ChoCH/BOS + bullish FVG exists
- **Short**: bearish ChoCH/BOS + bearish FVG exists
- **Stand aside**: no structural signal or conflicting directions

## Dependencies

```bash
pip install smartmoneyconcepts pandas numpy requests
```

## Parameters

| Parameter | Default | Description |
|------|--------|------|
| swing_length | 10 | Window for swing high/low detection |
| close_break | True | Whether BOS/ChoCH requires a closing-price break |

## Signal Convention

- `1` = long, `-1` = short, `0` = stand aside

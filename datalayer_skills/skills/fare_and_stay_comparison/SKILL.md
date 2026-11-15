---
name: fare-and-stay-comparison
description: Compare flights and stays on what matters to the person — for flights the route, fare, baggage, connections and total travel time; for stays the location, price per night and in total, amenities and cancellation terms — in one table each, with a recommendation and the booking links. Use it when the person asks which flight or which hotel to take.
license: BSD-3-Clause
version: 1.0.0
tags:
  - travel
  - flights
  - accommodation
  - comparison
author: Datalayer
metadata:
  visibility: public
  category: travel
---

# Fare and Stay Comparison Skill

How to compare flights and stays fairly, so that the cheapest-looking option is
not the dearest once bags, transfers and cancellation are counted.

## Required Environment Variables

- None required. The flights and stays tools it relies on have their own.

## Flights

Compare a short list, three to five, in one table:

| Column | What goes in it |
|---|---|
| Route | Airports, and each connection with its waiting time |
| Times | Departure and arrival, local time, and the total duration |
| Fare | The fare as the tool gave it, with its currency |
| Baggage | Personal item, cabin bag, checked bag included or not |
| Fare with bags | The fare with the bags the person needs, when the tool priced them; otherwise say they are extra |
| Risks | Self-transfer, overnight stopover, change of airport, a very short connection |
| Link | The booking link the tool returned |

Prefer the airport the person named; a cheaper airport further away counts the
transfer's time and cost.

## Stays

Compare a short list, three to five, in one table:

| Column | What goes in it |
|---|---|
| Place | Its name and its area, and the travel time to what the person will do most |
| Price | Per night and for the whole stay, with taxes when the tool gave them |
| Rating | The rating and the number of reviews, when the tool gave them |
| Amenities | What the person asked for: breakfast, a kitchen, parking, a lift, Wi-Fi |
| Cancellation | Free until when, partly refundable, or non-refundable |
| Link | The booking link the tool returned |

Without a stays tool, find stays with the maps tool (its places, their ratings
and their Maps links) and say that its prices are not known: the person checks
them on the link.

## Rules

- Recommend one, and say why in a sentence, against what the person said
  matters.
- **Never book and never pay**: give the links; the person books on the
  provider's site.
- **A price is a quote that can change**: the fare or rate at the time of the
  search, until the person books.
- Quote only what the tools returned; an empty cell says *not given*, never a
  guess.
- Compare like with like: the same dates, the same travellers, the same bags,
  the same currency.

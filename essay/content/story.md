# Startup opportunities identified via Hacker News conversations between 2025-26

Founders ask one question first. What hurts, for whom, and is anyone fixing it?

Hacker News is a year-long public log of people hitting problems. We read it at scale.

Every number here is a share of firsthand complaints on HN. It is not market size.

No comment text or usernames appear. Each finding links to its evidence instead.

The bars show a 50% range (thick) and a 95% range (thin). Faded means thin evidence.

We answer six questions. Each one tests something a real opportunity needs.

- Many people hit it.
- It hurts more than the talk suggests.
- It is growing, not fading.
- People already spend money or time to cope.
- Existing fixes fall short.
- Few people are building for it.

Four findings stand out.

- AI coding complaints jumped from 2.8% to 6.1% in one quarter. They stayed there.
- Consumer tech is 6.9% of talk but 17.1% of complaints.
- 60% of people whose paid products got worse already pay, switch, or quit.
- Rebuilding small tools draws 8 times more launches than its share of complaints.

## 0. The raw material

HN produced 3,991,507 comments between 28 September 2025 and 28 September 2026.

A cheap classifier, TypeSafe Jev, read a probability sample of 605,125 of them.

It asked one question first. Does the writer describe a problem they hit themselves?

About 6.4% do. That projects to roughly 235,000 firsthand problems across the year.

We then sorted each problem into 150 need cards. 58% fit a card cleanly.

<!-- chart:funnel-units -->

The monthly rate barely moves. It stays between 5.5% and 7.1% of comments.

So HN does not get angrier. What changes is what people complain about.

For a builder: the 58% on cards is the map. The other 42% is noise and one-offs.

## 1. What people complain about

Thirteen groups of needs cover the map. No single need dominates.

<!-- chart:voronoi-needs -->

Developer tools lead at 11.0% of firsthand problems. Devices and operating systems follow at 9.3%.

Consumer apps come third at 6.3%. The two AI groups add 9.9% together.

The biggest single need is broken, slow websites. It holds only 2.0% of problems.

<!-- chart:forest-top -->

This is a long tail. The top 20 needs hold about 22% of all problems.

The words people use show each group's texture.

<!-- chart:terms-columns -->

Who complains also differs sharply by group.

<!-- chart:role-mekko -->

Software engineers write 81% of AI coding complaints. End users write 62% of chatbot complaints.

Cloud problems split evenly between ops staff and ordinary users.

Students write 58% of learning complaints. Founders and managers show up in hiring and management.

For a builder: know who writes the complaint. That is who you would sell to.

## 2. Loud versus quiet

Talk and pain are different things. Some topics are all talk.

We compared each topic's share of all comments with its share of complaints.

<!-- chart:domain-morph -->

Consumer tech is 6.9% of all talk but 17.1% of complaints. That is 2.5 times.

Product design runs 1.9 times. Infrastructure and ops run 1.7 times.

Legal and government topics are the opposite. They are 12.7% of talk, 1.9% of complaints.

AI is 14.7% of talk but only 12.2% of complaints. People discuss it more than suffer it.

Some needs live inside one domain. Others appear everywhere.

<!-- chart:breadth-swarm -->

Hostile discussions, unreachable support, and arbitrary moderation span many domains.

Version control pain and database tuning stay inside software.

For a builder: broad needs suit platforms. Narrow needs suit a focused wedge product.

## 3. What changed

Six months is enough to see the ground move.

<!-- chart:need-stripes -->

AI coding complaints jumped from 2.8% to 6.1% in one quarter. They stayed there.

The next two quarters held between 5.5% and 5.9%.

AI chatbot complaints kept climbing all year, from 3.6% to 6.3%.

AI rose from 9.0% of problems in the first half to 13.0% in the second.

Developer tools fell from 13.9% to 8.9%. Cloud and ops fell from 5.2% to 2.8%.

<!-- chart:risers-fallers -->

The fastest risers are all AI. Coding costs and usage limits nearly doubled.

Changing AI plans and terms nearly tripled. Models that flatter and pad more than doubled.

Desktop Linux gaps and steep languages fell the most.

Every change shown survives a correction for testing many needs at once.

Each keeps its direction when we drop its biggest thread.

For a builder: the AI toolchain is where new pain appears fastest.

## 4. Pay, hack, or quit

A complaint is cheap. Paying, hacking, or quitting is a stronger signal.

<!-- chart:coping-triangle -->

Paid products getting worse leads. 60% of those writers already pay, switch, or quit.

Costly care and junk reviews follow near 58%.

Subscriptions replacing purchases reach 50%. Three in four name a money cost.

AI plans and terms reach 43%. AI coding costs reach 41%.

Other needs get hacked instead of bought.

Smart home cloud lock-in and switching AI tools both hit 66% workarounds.

People rebuild small tools themselves in 59% of those complaints.

<!-- chart:cost-radar -->

Some needs hurt more than others when they land.

Banned accounts with no appeal are the harshest. 66% reach a real cost or worse.

Third-party outages follow at 60%. Hacked accounts reach 54%.

For a builder: payment means a budget exists. Workarounds mean the pain is real but unmet.

## 5. Is anyone solving it

We checked three things. Replies, named tools, and product launches.

<!-- chart:closed-open -->

Replies rarely close the loop.

In the 40 biggest needs, 68 of 100 problems got no reply naming a fix.

Authors almost never come back to say it worked. That happens under 1% of the time.

Bad management and hostile discussions are nearly never solved in replies, at 97%.

False chatbot facts sit at 85%. Scams and spam sit at 85% too.

<!-- chart:tool-funnel -->

The same tools appear on both sides. The popular ones get blamed and recommended.

A few small tools are recommended unusually often. uBlock Origin, uv, and Jujutsu stand out.

Then we asked where builders actually launch.

We assigned a sample of 8,001 Show HN launches to the same 150 needs.

<!-- chart:builders-scatter -->

Builders crowd some needs. Rebuilding small tools gets 6.1% of launches but 0.8% of complaints.

That is eight times more launches than complaints.

Other needs get almost no launches. Early hardware failure with no repair got none.

Show HN is mostly software, so hardware needs draw few launches anyway.

Broken websites and updates that break devices got almost none too.

For a builder: pain with few launches is the gap. Crowded needs are a warning.

## 6. Where the openings are

Now we combine all six tests into one score.

You choose the weights. The ranking updates live.

<!-- chart:opportunity -->

With equal weights, five needs lead. Their order is not stable.

- Early failure with no repair.
- Data taken without consent.
- AI agents that write bad code.
- Clumsy login and two-factor flows.
- Broken, slow websites.

Ranks move under resampling. The dots show how far each rank can drift.

Switch to the underbuilt preset. Outages of code hosts and AI services rise to the top.

That preset leans on the Show HN sample. Read it as a lead.

Some needs cluster, so one product could serve several.

<!-- chart:bundles -->

Metered cost pain joins AI coding costs, cloud bills, and subscriptions.

Platform power joins changing AI terms, platform dependency, and devices losing support.

Everything-goes-down joins code hosting, AI, and third-party outages.

<!-- chart:profile -->

For a builder: pick one need. Follow its evidence. Then go talk to those people.

## How we know

This whole study cost $22.51 of classifier credit, over 501,082 calls.

<!-- chart:receipt -->

The median call took 260 milliseconds. The main screen took 2 hours 19 minutes.

We checked the classifier four ways.

<!-- chart:quality -->

In a blind human audit, its need card fit 95% of the time. A random card fit 60%.

On 226 invented test comments, it screened correctly 97% of the time.

It placed 90% of planted fake problems on the right card.

Rewording its instructions changed the card for about 8 to 9% of problems.

For a builder: a cheap classifier works if you measure its errors honestly.

## What could be wrong

Our choices shape the ranking. So we reran it under five other choices.

<!-- chart:spec-ranks -->

The top needs mostly hold their place. A few are fragile and marked.

Some needs rest on a few threads or a few loud people.

<!-- chart:concentration -->

Those are flagged. Treat them as leads, not findings.

Other limits matter too.

- HN is not the market. It skews toward developers.
- Every label is the classifier's call, audited only on a small sample.
- The screen misses some firsthand problems below its cutoff.
- 42% of problems fit no card.
- Shares compare topics. A falling share can mean others grew.

For a builder: trust the needs that survive every check. Then verify them in interviews.

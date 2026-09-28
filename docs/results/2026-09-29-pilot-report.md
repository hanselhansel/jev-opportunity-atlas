# Pilot report `pilot-20260929`

## Run

- `pilot-20260929`
- `pilot-20260929-packed`
- `pilot-20260929-injected`
- sample_id: `pilot-20260929`
- snapshot_id: `hn-2025-09-28_2026-09-28-v1`
- model: `jev-1.13.0`
- `pilot-20260929` `screen@1` sha256 `a7d3fb2e620e30732faa78c0a3d9591fd2aa9d7fb76dde9cafcc729f2d305aeb`
- `pilot-20260929` `facets@1` sha256 `6323ba5aed0b0391060521c8f8a8505c43caaf08c6325e7842e10424d69a0c26`
- `pilot-20260929-packed` `packed-screen@1` sha256 `79b54a3ce9c3c4c6e464c9cc14f3c9771b5dc1a46c4d6c2bf23841ec775a69d0`
- `pilot-20260929-injected` `screen@1` sha256 `a7d3fb2e620e30732faa78c0a3d9591fd2aa9d7fb76dde9cafcc729f2d305aeb`
- `pilot-20260929-injected` `facets@1` sha256 `6323ba5aed0b0391060521c8f8a8505c43caaf08c6325e7842e10424d69a0c26`
- window: 2026-09-28T23:33:24.102784+00:00 .. 2026-09-28T23:36:13.996430+00:00

## Cost

- screen (`pilot-20260929`; screen@1): $0.0665 over 2706 calls, 0 unknown attempts (calculated from reported usage; not provider-reconciled)
- facets (`pilot-20260929`; facets@1): $0.0635 over 897 calls, 0 unknown attempts (calculated from reported usage; not provider-reconciled)
- packed (`pilot-20260929-packed`; packed-screen@1): $0.0053 over 100 calls, 0 unknown attempts (calculated from reported usage; not provider-reconciled)
- injected (`pilot-20260929-injected`; facets@1, screen@1): $0.0016 over 40 calls, 0 unknown attempts (calculated from reported usage; not provider-reconciled)
- total: $0.1370 (calculated from reported usage; not provider-reconciled)
- pilot budget: $0.1370 committed of $0.5000 cap; $0.3630 remaining (calculated from reported usage; not provider-reconciled)
- account: $0.1370 committed of $25.0000; $24.8630 remaining (calculated from reported usage; not provider-reconciled)

## Tokens per call

- facets@1: n=917 mean=1681 p50=1581 p95=2216
- packed-screen@1: n=100 mean=1253 p50=1163 p95=1845
- screen@1: n=2726 mean=585 p50=539 p95=844
- nopain|L0|H1|ask (screen@1): n=20 mean=502 p50=502 p95=523
- nopain|L0|H1|other (screen@1): n=19 mean=499 p50=500 p95=505
- nopain|L0|H1|show (screen@1): n=20 mean=502 p50=500 p95=517
- nopain|L0|H1|story (screen@1): n=169 mean=502 p50=501 p95=519
- nopain|L0|H2|ask (screen@1): n=20 mean=500 p50=499 p95=509
- nopain|L0|H2|other (screen@1): n=20 mean=498 p50=496 p95=504
- nopain|L0|H2|show (screen@1): n=20 mean=500 p50=499 p95=512
- nopain|L0|H2|story (screen@1): n=186 mean=502 p50=501 p95=516
- nopain|L1|H1|ask (screen@1): n=20 mean=526 p50=521 p95=553
- nopain|L1|H1|other (screen@1): n=20 mean=529 p50=520 p95=559
- nopain|L1|H1|show (screen@1): n=20 mean=532 p50=530 p95=554
- nopain|L1|H1|story (screen@1): n=431 mean=532 p50=530 p95=561
- nopain|L1|H2|ask (screen@1): n=20 mean=537 p50=541 p95=558
- nopain|L1|H2|other (screen@1): n=20 mean=522 p50=518 p95=545
- nopain|L1|H2|show (screen@1): n=20 mean=532 p50=531 p95=555
- nopain|L1|H2|story (screen@1): n=457 mean=532 p50=529 p95=565
- nopain|L2|H1|ask (screen@1): n=20 mean=632 p50=614 p95=748
- nopain|L2|H1|other (screen@1): n=20 mean=632 p50=616 p95=703
- nopain|L2|H1|show (screen@1): n=20 mean=628 p50=616 p95=724
- nopain|L2|H1|story (screen@1): n=222 mean=617 p50=604 p95=711
- nopain|L2|H2|ask (screen@1): n=20 mean=633 p50=616 p95=710
- nopain|L2|H2|other (screen@1): n=20 mean=612 p50=607 p95=675
- nopain|L2|H2|show (screen@1): n=20 mean=614 p50=604 p95=671
- nopain|L2|H2|story (screen@1): n=219 mean=615 p50=606 p95=714
- nopain|L3|H1|ask (screen@1): n=20 mean=920 p50=824 p95=1501
- nopain|L3|H1|other (screen@1): n=2 mean=776 p50=776 p95=813
- nopain|L3|H1|show (screen@1): n=20 mean=845 p50=802 p95=1060
- nopain|L3|H1|story (screen@1): n=23 mean=925 p50=865 p95=1403
- nopain|L3|H2|ask (screen@1): n=20 mean=889 p50=856 p95=1175
- nopain|L3|H2|other (screen@1): n=2 mean=764 p50=764 p95=774
- nopain|L3|H2|show (screen@1): n=20 mean=894 p50=826 p95=1319
- nopain|L3|H2|story (screen@1): n=22 mean=960 p50=866 p95=1377
- pain|L0|H1|ask (screen@1): n=20 mean=504 p50=503 p95=518
- pain|L0|H1|show (screen@1): n=20 mean=505 p50=502 p95=525
- pain|L0|H1|story (screen@1): n=20 mean=504 p50=502 p95=516
- pain|L0|H2|ask (screen@1): n=20 mean=503 p50=503 p95=509
- pain|L0|H2|show (screen@1): n=20 mean=501 p50=502 p95=509
- pain|L0|H2|story (screen@1): n=20 mean=501 p50=501 p95=508
- pain|L1|H1|ask (screen@1): n=20 mean=533 p50=535 p95=560
- pain|L1|H1|other (screen@1): n=7 mean=533 p50=537 p95=546
- pain|L1|H1|show (screen@1): n=20 mean=537 p50=538 p95=566
- pain|L1|H1|story (screen@1): n=21 mean=547 p50=539 p95=563
- pain|L1|H2|ask (screen@1): n=20 mean=539 p50=544 p95=563
- pain|L1|H2|other (screen@1): n=5 mean=536 p50=549 p95=553
- pain|L1|H2|show (screen@1): n=20 mean=537 p50=534 p95=561
- pain|L1|H2|story (screen@1): n=22 mean=532 p50=532 p95=557
- pain|L2|H1|ask (screen@1): n=20 mean=630 p50=610 p95=711
- pain|L2|H1|other (screen@1): n=10 mean=615 p50=608 p95=682
- pain|L2|H1|show (screen@1): n=20 mean=650 p50=652 p95=733
- pain|L2|H1|story (screen@1): n=33 mean=618 p50=610 p95=705
- pain|L2|H2|ask (screen@1): n=20 mean=664 p50=651 p95=791
- pain|L2|H2|other (screen@1): n=2 mean=608 p50=608 p95=616
- pain|L2|H2|show (screen@1): n=20 mean=638 p50=624 p95=734
- pain|L2|H2|story (screen@1): n=32 mean=638 p50=630 p95=727
- pain|L3|H1|ask (screen@1): n=20 mean=997 p50=909 p95=1517
- pain|L3|H1|show (screen@1): n=20 mean=967 p50=862 p95=1156
- pain|L3|H1|story (screen@1): n=20 mean=908 p50=852 p95=1364
- pain|L3|H2|ask (screen@1): n=20 mean=894 p50=877 p95=1076
- pain|L3|H2|other (screen@1): n=2 mean=888 p50=888 p95=1020
- pain|L3|H2|show (screen@1): n=20 mean=965 p50=910 p95=1302
- pain|L3|H2|story (screen@1): n=20 mean=902 p50=834 p95=1136

## Firsthand rate per design stratum

- nopain|L0|H1|ask: 20/20 screened, 2 firsthand, raw rate 0.100; p_h=0.100 (from nopain|L0|H1|ask), c_h=502 tokens (from nopain|L0|H1|ask)
- nopain|L0|H1|other: 20/20 screened, 0 firsthand, raw rate 0.000; p_h=0.000 (from nopain|L0|H1|other), c_h=501 tokens (from nopain|L0)
- nopain|L0|H1|show: 20/20 screened, 1 firsthand, raw rate 0.050; p_h=0.050 (from nopain|L0|H1|show), c_h=502 tokens (from nopain|L0|H1|show)
- nopain|L0|H1|story: 169/169 screened, 6 firsthand, raw rate 0.036; p_h=0.036 (from nopain|L0|H1|story), c_h=502 tokens (from nopain|L0|H1|story)
- nopain|L0|H2|ask: 20/20 screened, 1 firsthand, raw rate 0.050; p_h=0.050 (from nopain|L0|H2|ask), c_h=500 tokens (from nopain|L0|H2|ask)
- nopain|L0|H2|other: 20/20 screened, 3 firsthand, raw rate 0.150; p_h=0.150 (from nopain|L0|H2|other), c_h=498 tokens (from nopain|L0|H2|other)
- nopain|L0|H2|show: 20/20 screened, 2 firsthand, raw rate 0.100; p_h=0.100 (from nopain|L0|H2|show), c_h=500 tokens (from nopain|L0|H2|show)
- nopain|L0|H2|story: 186/186 screened, 5 firsthand, raw rate 0.027; p_h=0.027 (from nopain|L0|H2|story), c_h=502 tokens (from nopain|L0|H2|story)
- nopain|L1|H1|ask: 20/20 screened, 5 firsthand, raw rate 0.250; p_h=0.250 (from nopain|L1|H1|ask), c_h=526 tokens (from nopain|L1|H1|ask)
- nopain|L1|H1|other: 20/20 screened, 3 firsthand, raw rate 0.150; p_h=0.150 (from nopain|L1|H1|other), c_h=529 tokens (from nopain|L1|H1|other)
- nopain|L1|H1|show: 20/20 screened, 6 firsthand, raw rate 0.300; p_h=0.300 (from nopain|L1|H1|show), c_h=532 tokens (from nopain|L1|H1|show)
- nopain|L1|H1|story: 431/431 screened, 41 firsthand, raw rate 0.095; p_h=0.095 (from nopain|L1|H1|story), c_h=532 tokens (from nopain|L1|H1|story)
- nopain|L1|H2|ask: 20/20 screened, 2 firsthand, raw rate 0.100; p_h=0.100 (from nopain|L1|H2|ask), c_h=537 tokens (from nopain|L1|H2|ask)
- nopain|L1|H2|other: 20/20 screened, 5 firsthand, raw rate 0.250; p_h=0.250 (from nopain|L1|H2|other), c_h=522 tokens (from nopain|L1|H2|other)
- nopain|L1|H2|show: 20/20 screened, 4 firsthand, raw rate 0.200; p_h=0.200 (from nopain|L1|H2|show), c_h=532 tokens (from nopain|L1|H2|show)
- nopain|L1|H2|story: 457/457 screened, 39 firsthand, raw rate 0.085; p_h=0.085 (from nopain|L1|H2|story), c_h=532 tokens (from nopain|L1|H2|story)
- nopain|L2|H1|ask: 20/20 screened, 5 firsthand, raw rate 0.250; p_h=0.250 (from nopain|L2|H1|ask), c_h=632 tokens (from nopain|L2|H1|ask)
- nopain|L2|H1|other: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from nopain|L2|H1|other), c_h=632 tokens (from nopain|L2|H1|other)
- nopain|L2|H1|show: 20/20 screened, 6 firsthand, raw rate 0.300; p_h=0.300 (from nopain|L2|H1|show), c_h=628 tokens (from nopain|L2|H1|show)
- nopain|L2|H1|story: 222/222 screened, 25 firsthand, raw rate 0.113; p_h=0.113 (from nopain|L2|H1|story), c_h=617 tokens (from nopain|L2|H1|story)
- nopain|L2|H2|ask: 20/20 screened, 3 firsthand, raw rate 0.150; p_h=0.150 (from nopain|L2|H2|ask), c_h=633 tokens (from nopain|L2|H2|ask)
- nopain|L2|H2|other: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from nopain|L2|H2|other), c_h=612 tokens (from nopain|L2|H2|other)
- nopain|L2|H2|show: 20/20 screened, 6 firsthand, raw rate 0.300; p_h=0.300 (from nopain|L2|H2|show), c_h=614 tokens (from nopain|L2|H2|show)
- nopain|L2|H2|story: 219/219 screened, 39 firsthand, raw rate 0.178; p_h=0.178 (from nopain|L2|H2|story), c_h=615 tokens (from nopain|L2|H2|story)
- nopain|L3|H1|ask: 20/20 screened, 7 firsthand, raw rate 0.350; p_h=0.350 (from nopain|L3|H1|ask), c_h=920 tokens (from nopain|L3|H1|ask)
- nopain|L3|H1|other: 2/2 screened, 1 firsthand, raw rate 0.500; p_h=0.326 (from nopain|L3), c_h=902 tokens (from nopain|L3)
- nopain|L3|H1|show: 20/20 screened, 10 firsthand, raw rate 0.500; p_h=0.500 (from nopain|L3|H1|show), c_h=845 tokens (from nopain|L3|H1|show)
- nopain|L3|H1|story: 23/23 screened, 3 firsthand, raw rate 0.130; p_h=0.130 (from nopain|L3|H1|story), c_h=925 tokens (from nopain|L3|H1|story)
- nopain|L3|H2|ask: 20/20 screened, 6 firsthand, raw rate 0.300; p_h=0.300 (from nopain|L3|H2|ask), c_h=889 tokens (from nopain|L3|H2|ask)
- nopain|L3|H2|other: 2/2 screened, 0 firsthand, raw rate 0.000; p_h=0.326 (from nopain|L3), c_h=902 tokens (from nopain|L3)
- nopain|L3|H2|show: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from nopain|L3|H2|show), c_h=894 tokens (from nopain|L3|H2|show)
- nopain|L3|H2|story: 22/22 screened, 6 firsthand, raw rate 0.273; p_h=0.273 (from nopain|L3|H2|story), c_h=960 tokens (from nopain|L3|H2|story)
- pain|L0|H1|ask: 20/20 screened, 6 firsthand, raw rate 0.300; p_h=0.300 (from pain|L0|H1|ask), c_h=504 tokens (from pain|L0|H1|ask)
- pain|L0|H1|show: 20/20 screened, 8 firsthand, raw rate 0.400; p_h=0.400 (from pain|L0|H1|show), c_h=505 tokens (from pain|L0|H1|show)
- pain|L0|H1|story: 20/20 screened, 7 firsthand, raw rate 0.350; p_h=0.350 (from pain|L0|H1|story), c_h=504 tokens (from pain|L0|H1|story)
- pain|L0|H2|ask: 20/20 screened, 10 firsthand, raw rate 0.500; p_h=0.500 (from pain|L0|H2|ask), c_h=503 tokens (from pain|L0|H2|ask)
- pain|L0|H2|show: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from pain|L0|H2|show), c_h=501 tokens (from pain|L0|H2|show)
- pain|L0|H2|story: 20/20 screened, 10 firsthand, raw rate 0.500; p_h=0.500 (from pain|L0|H2|story), c_h=501 tokens (from pain|L0|H2|story)
- pain|L1|H1|ask: 20/20 screened, 12 firsthand, raw rate 0.600; p_h=0.600 (from pain|L1|H1|ask), c_h=533 tokens (from pain|L1|H1|ask)
- pain|L1|H1|other: 7/7 screened, 1 firsthand, raw rate 0.143; p_h=0.422 (from pain|L1), c_h=537 tokens (from pain|L1)
- pain|L1|H1|show: 20/20 screened, 12 firsthand, raw rate 0.600; p_h=0.600 (from pain|L1|H1|show), c_h=537 tokens (from pain|L1|H1|show)
- pain|L1|H1|story: 21/21 screened, 6 firsthand, raw rate 0.286; p_h=0.286 (from pain|L1|H1|story), c_h=547 tokens (from pain|L1|H1|story)
- pain|L1|H2|ask: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from pain|L1|H2|ask), c_h=539 tokens (from pain|L1|H2|ask)
- pain|L1|H2|other: 5/5 screened, 0 firsthand, raw rate 0.000; p_h=0.422 (from pain|L1), c_h=537 tokens (from pain|L1)
- pain|L1|H2|show: 20/20 screened, 11 firsthand, raw rate 0.550; p_h=0.550 (from pain|L1|H2|show), c_h=537 tokens (from pain|L1|H2|show)
- pain|L1|H2|story: 22/22 screened, 6 firsthand, raw rate 0.273; p_h=0.273 (from pain|L1|H2|story), c_h=532 tokens (from pain|L1|H2|story)
- pain|L2|H1|ask: 20/20 screened, 8 firsthand, raw rate 0.400; p_h=0.400 (from pain|L2|H1|ask), c_h=630 tokens (from pain|L2|H1|ask)
- pain|L2|H1|other: 10/10 screened, 6 firsthand, raw rate 0.600; p_h=0.484 (from pain|L2), c_h=636 tokens (from pain|L2)
- pain|L2|H1|show: 20/20 screened, 13 firsthand, raw rate 0.650; p_h=0.650 (from pain|L2|H1|show), c_h=650 tokens (from pain|L2|H1|show)
- pain|L2|H1|story: 33/33 screened, 12 firsthand, raw rate 0.364; p_h=0.364 (from pain|L2|H1|story), c_h=618 tokens (from pain|L2|H1|story)
- pain|L2|H2|ask: 20/20 screened, 12 firsthand, raw rate 0.600; p_h=0.600 (from pain|L2|H2|ask), c_h=664 tokens (from pain|L2|H2|ask)
- pain|L2|H2|other: 2/2 screened, 1 firsthand, raw rate 0.500; p_h=0.484 (from pain|L2), c_h=636 tokens (from pain|L2)
- pain|L2|H2|show: 20/20 screened, 9 firsthand, raw rate 0.450; p_h=0.450 (from pain|L2|H2|show), c_h=638 tokens (from pain|L2|H2|show)
- pain|L2|H2|story: 32/32 screened, 15 firsthand, raw rate 0.469; p_h=0.469 (from pain|L2|H2|story), c_h=638 tokens (from pain|L2|H2|story)
- pain|L3|H1|ask: 20/20 screened, 8 firsthand, raw rate 0.400; p_h=0.400 (from pain|L3|H1|ask), c_h=997 tokens (from pain|L3|H1|ask)
- pain|L3|H1|show: 20/20 screened, 10 firsthand, raw rate 0.500; p_h=0.500 (from pain|L3|H1|show), c_h=967 tokens (from pain|L3|H1|show)
- pain|L3|H1|story: 20/20 screened, 7 firsthand, raw rate 0.350; p_h=0.350 (from pain|L3|H1|story), c_h=908 tokens (from pain|L3|H1|story)
- pain|L3|H2|ask: 20/20 screened, 10 firsthand, raw rate 0.500; p_h=0.500 (from pain|L3|H2|ask), c_h=894 tokens (from pain|L3|H2|ask)
- pain|L3|H2|other: 2/2 screened, 1 firsthand, raw rate 0.500; p_h=0.451 (from pain|L3), c_h=938 tokens (from pain|L3)
- pain|L3|H2|show: 20/20 screened, 11 firsthand, raw rate 0.550; p_h=0.550 (from pain|L3|H2|show), c_h=965 tokens (from pain|L3|H2|show)
- pain|L3|H2|story: 20/20 screened, 8 firsthand, raw rate 0.400; p_h=0.400 (from pain|L3|H2|story), c_h=902 tokens (from pain|L3|H2|story)

## Latency

- `pilot-20260929`: p50=247 ms p95=324 ms wall=148.5 s
- `pilot-20260929-packed`: p50=248 ms p95=328 ms wall=3.5 s
- `pilot-20260929-injected`: p50=272 ms p95=320 ms wall=1.9 s

## Answer distributions

- facets@1 abandoned: noul n=897 hist=[658, 112, 41, 21, 24, 16, 8, 7, 6, 4]
- facets@1 cost_customers: noul n=897 hist=[609, 152, 67, 18, 20, 13, 8, 4, 6, 0]
- facets@1 cost_money: noul n=897 hist=[765, 54, 20, 12, 8, 14, 3, 6, 9, 6]
- facets@1 cost_reliability: noul n=897 hist=[601, 115, 33, 28, 22, 23, 11, 23, 25, 16]
- facets@1 cost_time: noul n=897 hist=[413, 230, 90, 37, 30, 17, 16, 24, 23, 17]
- facets@1 domain: choice business_operations=7 consumer_tech=108 data_ml_ai=123 education_learning=16 finance_payments=16 hardware_electronics=22 health_medical=22 home_life=37 infrastructure_ops=42 legal_government=40 media_publishing=27 mixed=1 other=21 product_design=49 sales_marketing=16 science_research=10 security_privacy=54 software_development=234 unclear=9 work_careers=43
- facets@1 jurisdiction: choice australia=2 canada=1 china=4 eu=9 india=3 none=831 other=9 uk=6 us=32
- facets@1 paid: noul n=897 hist=[765, 54, 32, 13, 7, 3, 11, 6, 5, 1]
- facets@1 pain_sentence: choice s0=393 s1=227 s10=9 s11=5 s12=1 s13=3 s14=2 s15=5 s17=1 s2=101 s20=1 s21=2 s24=1 s27=1 s3=45 s30=1 s4=32 s48=1 s5=19 s6=19 s7=18 s8=4 s9=6
- facets@1 resolution: choice resolved=130 unclear=25 unresolved=742
- facets@1 severity: score mean=0.673 n=897
- facets@1 specificity: score mean=2.059 n=897
- facets@1 switched: noul n=897 hist=[735, 73, 29, 14, 15, 10, 9, 4, 7, 1]
- facets@1 timing: choice current=715 historical=140 hypothetical=27 unclear=15
- facets@1 tried_alternatives: noul n=897 hist=[303, 182, 96, 59, 50, 39, 38, 46, 42, 42]
- facets@1 user_role: choice data_ml_practitioner=25 end_user_consumer=310 founder_executive=41 freelancer_consultant=10 manager=8 ops_sre_it=17 other=19 product_or_designer=12 researcher_academic=11 software_engineer=269 student=5 unclear=170
- facets@1 workaround: noul n=897 hist=[334, 172, 100, 56, 40, 34, 39, 41, 49, 32]
- screen@1 account_type: choice firsthand_account=792 general_opinion=1215 joke_or_sarcasm=194 other=69 product_pitch=95 question_or_request=292 secondhand_report=50
- screen@1 firsthand_problem: noul n=2707 hist=[1330, 502, 191, 99, 78, 70, 71, 59, 91, 216]

## Screen gate preview

- screen@1 firsthand noul share >= 0.3: 0.257, >= 0.5: 0.187, >= 0.7: 0.139 (n=2707)
- problem evidence in facets@1 = max(workaround, cost_time, cost_money, cost_reliability, cost_customers noul) >= 0.5
- below-gate random comments: 201; with problem evidence: 27; weighted estimate the gate would drop in the pilot sample: 270.1 (= n_evidence / selection_prob)

## Packed experiment

- n=500 pearson=0.962 agreement@0.5=0.968 mean_abs_diff=0.045
- tokens/comment single=591.0 packed=250.6

## Injected cases

- overall: 19/20 correct (accuracy 0.950, 0 missing)
- disguised_pitch: 4/5 correct (0.800)
- fake_label: 5/5 correct (1.000)
- genuine_override_no: 5/5 correct (1.000)
- override_yes: 5/5 correct (1.000)

## Projection

- $5.00: n=198076, expected firsthand 63474.6, largest weight 50, expected cost $5.0000
- $6.50: n=261374, expected firsthand 83526.0, largest weight 50, expected cost $6.5000
- $8.00: n=326815, expected firsthand 101960.9, largest weight 50, expected cost $8.0000

## Calibration

- not available


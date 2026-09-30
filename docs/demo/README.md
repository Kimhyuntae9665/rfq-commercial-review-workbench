# Actual UI gallery
01–07 are actual browser captures using deterministic baseline extraction. Browser hostile-markup/large-integer/longlabel assertions use explicit temporary display-state mocks; those assertions are not screenshots of successful live inference.
08–12 are actual GET displays of three stored qwen3:4b API proposals which passed full-cell source validation. Source confirmation, cost12→30 and packet acknowledgement were performed by an automated synthetic demo script. Recording made0modelrequests; earlier API extraction made3 sequential requests.
No images were composited, success text edited, or private account/PC/SSH information included. Viewports contain only synthetic demo identities and synthetic source data.

| Image | State |
|---|---|
| ![원문 확인](01-source-confirmation.png) | Baseline full quote |
| ![수요12](02-demand-12.png) | B→A, Cexcluded |
| ![검토](03-packet-reviewed.png) | Specific baseline packet ack |
| ![조건 변경](04-changed-scenario.png) | Dirty scenario needs recalculation |
| ![수요30](05-demand-30.png) | A→B, fixedcolumns |
| ![reflow](06-zoom-200.png) | 200%-equivalent CSSreflow |
| ![mobile](07-mobile.png) | Narrowviewport |
| ![실제 모델](08-actual-model-proposals.png) | Stored actual3modelproposals |
| ![실제 인용](09-actual-model-source.png) | Actual source quote highlight |
| ![모델12](10-actual-model-demand12.png) | Confirmed actualmodel terms, CPUcost |
| ![모델30](11-actual-model-demand30.png) | CPUscenario reversal |
| ![모델검토](12-actual-model-reviewed.png) | Synthetic demo packet ack |

[Actual workflow video](video/workflow.mp4). Silent1440×1000 H264.27 original native JPEG viewport frames with captured monotonic timing; ffmpeg resamples to30fps and repeats holds. This is a browser-frame sequence, not an unbroken screen recording. Native frames and manifest are retained. No additional success overlays were added.

# Measurements from the deployed system

These observations come from the original Galaxy A52s deployment. The reference implementation uses a public Ava preset, native playback pace and no CPU affinity pinning; these figures are not benchmarks of a fresh clone.


| Test | Result | Timing boundary |
| --- | --- | --- |
| Warm INT8 synthesis on the Galaxy A52s, 24 replies | First PCM **279–360 ms**, median **288 ms**. Native real-time factor **0.838–1.004×**, median **0.942×**. | From input-token arrival. First PCM can contain silence. The RTF denominator is native generated audio duration, before tempo and pause processing. |
| Voice pipeline, 120 turns with outgoing audio | **1.22 s** median and **7.30 s** at the 90th percentile. | End of capture to first outgoing audio, which can be the thinking cue. Mixed normal use and test replays. |
| Wake-word detector, 20-clip offline replay | The original deployed classifier detected 10/10 intended calls and falsely triggered on 5/10 negatives. The replacement trial detected 8/10 intended calls and falsely triggered on 0/10 negatives. | Small offline comparison. An unattended room false-wake rate has yet to be measured. |

The [November 3 synthesis summary](../site/data/synthesis-2026-11-03.json) records three threads, CPU spinning, and two-frame codec batches after the first frame. Its first signal-bearing PCM chunk arrived in **279–416 ms**, median **288 ms**. That boundary uses a normalized sample-amplitude threshold of 0.005. Speaker onset was outside this test.

Native RTF is generation time divided by native audio duration, before the server's 1.10× tempo, pause processing, and protective tail. At the faster 1.10 playback pace, the recorded chunk arrivals needed at most **169 ms** of extra startup buffer. The earlier FP32 run took 1.70–1.89× native audio duration across three replies. Precision, thread count, and codec scheduling differed between runs.

Two handset microphone replays illustrate the timing boundaries. Capture end to first outgoing audio took **1,295 ms** for a fresh reply with a cue and **1,064 ms** for a pre-generated clock reply. Bridge request to first answer PCM took **1,147 ms** and **7 ms**, respectively. Both received playback acknowledgements. Each route has one observation, and the two clocks start at different points.

## What remains open

The 20-clip wake trial was too small to establish unattended room reliability, so the console uses tap-to-talk. Recognition in noise, long answers, thermal behavior and playback under network loss need broader everyday testing.

The original system also uses a 1,522-clip clock/confirmation bank, tempo and guarded pause processing, optional Wikipedia/Qwen answers, VACA-specific playback hooks and a wake guard. Those deployment extensions are described by the figures; they are outside the reference implementation in this repository.

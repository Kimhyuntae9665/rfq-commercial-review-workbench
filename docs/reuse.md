# Reuse
The bounded localhost transport and its portable shared lock/timeout regressions were copied from project02 source727dbf7fed8dcdaad767e0e9a15a9fb4888c5d55. Source SHA256 of copied llm.py: ba5c41e652875d39ce7e1f5639027c0b08866120a8068f84320f2e3d6885a14e. Its document-specific adapter was replaced with independent offer extraction.
No import or write dependency on01/02. Shared runtime: user-private ~/.cache/ax-lab/runtime/inference.lock and inference.lock.blocked; timeout failclosed/no automatic retry. Exact policy follows the copied transport; no server stop or automatic barrier deletion.
No n8n template JSON/code/comments were copied. Community workflow ideas may be cited byURL only unless explicit redistribution rights are verified.

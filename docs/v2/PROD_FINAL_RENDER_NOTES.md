# K-Sound Hub V2 final-render playback

This tranche replaces the playback core with a centralized mixer process.

Expected runtime shape:

- no playback `pipewire -c filter-chain.conf` process for V2 playback
- one `v2_final_mixer.py` process
- one `parec` capture per visible playback channel
- one `pacat` final renderer per active physical target

Micro/return-mic are intentionally still inherited from the existing backend.

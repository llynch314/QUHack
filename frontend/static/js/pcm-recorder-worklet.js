// AudioWorklet: converts microphone audio to 16 kHz mono 16-bit PCM (what Gemini Live expects)
// and posts ~100 ms chunks to the main thread, plus a level value for the meter.
class PcmRecorder extends AudioWorkletProcessor {
    constructor() {
        super();
        this.ratio = sampleRate / 16000;   // `sampleRate` is the AudioContext rate (e.g. 48000)
        this.pos = 0;                      // fractional read position into pending input
        this.pending = [];                 // input samples not yet consumed
        this.out = new Int16Array(1600);   // 100 ms at 16 kHz
        this.outLen = 0;
    }

    process(inputs) {
        const channel = inputs[0] && inputs[0][0];
        if (!channel) return true;

        let sum = 0;
        for (let i = 0; i < channel.length; i++) { this.pending.push(channel[i]); sum += channel[i] * channel[i]; }
        this.port.postMessage({ level: Math.sqrt(sum / channel.length) });

        // Downsample by averaging each window of input samples into one output sample.
        while (this.pos + this.ratio <= this.pending.length) {
            const start = Math.floor(this.pos), end = Math.floor(this.pos + this.ratio);
            let acc = 0;
            for (let i = start; i < end; i++) acc += this.pending[i];
            const s = Math.max(-1, Math.min(1, acc / Math.max(1, end - start)));
            this.out[this.outLen++] = s < 0 ? s * 0x8000 : s * 0x7fff;
            this.pos += this.ratio;
            if (this.outLen === this.out.length) {
                const chunk = this.out.slice(0).buffer;
                this.port.postMessage({ pcm: chunk }, [chunk]);
                this.outLen = 0;
            }
        }
        const used = Math.floor(this.pos);
        this.pending = this.pending.slice(used);
        this.pos -= used;
        return true;
    }
}
registerProcessor('pcm-recorder', PcmRecorder);

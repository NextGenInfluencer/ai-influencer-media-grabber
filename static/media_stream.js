/* Buffer SSE frames across network chunks, including split UTF-8 characters. */
class MediaEventDecoder {
    constructor() {
        this.decoder = new TextDecoder();
        this.pending = '';
    }
    decode(value) {
        this.pending += this.decoder.decode(value, {stream: true});
        const frames = this.pending.split(/\r?\n\r?\n/);
        this.pending = frames.pop();
        return frames;
    }
}
if (typeof module !== 'undefined') module.exports = {MediaEventDecoder};

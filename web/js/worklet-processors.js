// AudioWorklet processor (thread audio). Digabung dengan dsp-core.js oleh worklets.js.
/* global registerProcessor, AudioWorkletProcessor, FDNCore, WarmthCore, ComfortCore */

class FDNProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.core = new FDNCore(opts.processorOptions);
    this.alive = true;
    this.port.onmessage = (e) => { if (e.data === "stop") this.alive = false; };
  }
  process(inputs, outputs) {
    const inp = inputs[0], out = outputs[0];
    const n = out[0].length;
    const zero = this.zero || (this.zero = new Float32Array(n));
    const l = inp[0] || zero, r = inp[1] || inp[0] || zero;
    this.core.process(l, r, out[0], out[1] || out[0], n);
    return this.alive;
  }
}
registerProcessor("fdn-reverb", FDNProcessor);

class WarmthProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.core = new WarmthCore(opts.processorOptions);
    this.alive = true;
    this.port.onmessage = (e) => {
      if (e.data === "stop") this.alive = false;
      else if (e.data && e.data.type === "set") this.core.set(e.data.params);
    };
  }
  process(inputs, outputs) {
    const inp = inputs[0], out = outputs[0];
    const n = out[0].length;
    if (!inp.length) { out[0].fill(0); if (out[1]) out[1].fill(0); return this.alive; }
    this.core.process(inp[0], inp[1] || inp[0], out[0], out[1] || out[0], n);
    return this.alive;
  }
}
registerProcessor("warmth", WarmthProcessor);

class ComfortProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    this.core = new ComfortCore(opts.processorOptions);
    this.alive = true;
    this.port.onmessage = (e) => {
      if (e.data === "stop") this.alive = false;
      else if (e.data && e.data.type === "set") this.core.set(e.data.params);
    };
  }
  process(inputs, outputs) {
    const inp = inputs[0], out = outputs[0];
    const n = out[0].length;
    if (!inp.length) { out[0].fill(0); if (out[1]) out[1].fill(0); return this.alive; }
    this.core.process(inp[0], inp[1] || inp[0], out[0], out[1] || out[0], n);
    return this.alive;
  }
}
registerProcessor("comfort", ComfortProcessor);

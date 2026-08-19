/*!
 * Petabyte Edge-Inference SDK (prototype) — v0.1.0
 *
 * Run an AI feature on the VISITOR'S OWN GPU via WebGPU (free to the site), and fall back
 * to a metered Petabyte GPU through the API when the visitor has no capable GPU. This is the
 * honest, consent-based inverse of "mine the visitor for ads": the user asked for the AI
 * feature, their device serves it, and Petabyte only earns on the paid fallback.
 *
 * Usage:
 *   PetabyteEdge.configure({ apiBase: 'https://petabyte.market', model: '<hf-model-id>' });
 *   const r = await PetabyteEdge.infer('Summarize this: ...');
 *   // r = { source: 'on-device' | 'petabyte', model, text, meta? }
 *
 * On-device path uses @huggingface/transformers (WebGPU) loaded from a CDN allowed by the
 * page CSP. Real on-device model WEIGHTS are fetched from the model host — which the default
 * site CSP (`connect-src 'self'`) blocks on purpose. When weights can't load (CSP, no WebGPU,
 * OOM, any error) the SDK transparently falls back to the API. To enable true on-device
 * inference, the operator sets EDGE_INFERENCE_ENABLED=true (see docs/EDGE_INFERENCE.md), which
 * widens the CSP to permit the model host. Default-off keeps production locked down.
 *
 * No dependency, no build step, no globals besides window.PetabyteEdge.
 */
(function (global) {
  'use strict';

  var DEFAULTS = {
    apiBase: '',                                   // same-origin by default
    apiKey: '',                                    // inference-scoped key: enables the METERED fallback
    model: 'onnx-community/Qwen2.5-0.5B-Instruct', // small instruct model for the demo
    allowOnDevice: true,
    maxTokens: 128,
    // ESM build of transformers.js; jsdelivr is allowed by the site's script-src CSP.
    transformersUrl: 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.0.2'
  };
  var cfg = Object.assign({}, DEFAULTS);
  var _gen = null, _genModel = null;

  function configure(o) { Object.assign(cfg, o || {}); return cfg; }

  // What can this browser actually do? Cheap, side-effect-free, safe to call on page load.
  async function capabilities() {
    var out = { webgpu: false, f16: false, adapter: {} };
    try {
      if (global.navigator && navigator.gpu) {
        var a = await navigator.gpu.requestAdapter();
        if (a) {
          out.webgpu = true;
          out.f16 = !!(a.features && a.features.has && a.features.has('shader-f16'));
          try { out.adapter = a.info || (a.requestAdapterInfo ? await a.requestAdapterInfo() : {}); } catch (e) {}
        }
      }
    } catch (e) {}
    return out;
  }

  async function _ensureOnDevice(model, onProgress) {
    if (_gen && _genModel === model) return _gen;
    // Dynamic import of the ESM module (governed by script-src, not connect-src).
    var t = await import(/* @vite-ignore */ cfg.transformersUrl);
    if (t.env) { t.env.allowLocalModels = false; }
    _gen = await t.pipeline('text-generation', model, {
      device: 'webgpu', dtype: 'q4', progress_callback: onProgress || undefined
    });
    _genModel = model;
    return _gen;
  }

  async function _onDevice(prompt, opts) {
    var model = opts.model || cfg.model;
    var gen = await _ensureOnDevice(model, opts.onProgress);
    var messages = [{ role: 'user', content: prompt }];
    var res = await gen(messages, { max_new_tokens: opts.maxTokens || cfg.maxTokens, do_sample: false });
    var text = '';
    try {
      text = res[0].generated_text;
      if (Array.isArray(text)) text = text[text.length - 1].content; // chat format
    } catch (e) { text = String(res); }
    return { source: 'on-device', model: model, text: text };
  }

  async function _fallback(prompt, opts) {
    var base = (opts.apiBase != null ? opts.apiBase : cfg.apiBase) || '';
    var key = (opts.apiKey != null ? opts.apiKey : cfg.apiKey) || '';
    if (key) {
      // Real, metered inference: the authenticated pay-per-token API. /edge/infer never
      // proxies the GPU pool (it would be an unauthenticated free-compute hole).
      var rr = await fetch(base + '/v1/chat/completions', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-KEY': key },
        body: JSON.stringify({ prompt: prompt, model: opts.model || cfg.model,
                               max_tokens: opts.maxTokens || cfg.maxTokens })
      });
      if (!rr.ok) {
        var ee = ''; try { ee = await rr.text(); } catch (_) {}
        throw new Error('petabyte inference HTTP ' + rr.status + ' ' + ee);
      }
      var bb = await rr.json();
      var txt = '';
      try { txt = bb.choices[0].message.content || ''; } catch (_) { txt = bb.text || ''; }
      return { source: 'petabyte', model: bb.model || opts.model || cfg.model, text: txt, meta: bb };
    }
    // Keyless: the public prototype placeholder (clearly labelled, never a real model).
    var r = await fetch(base + '/edge/infer', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt, model: opts.model || cfg.model, max_tokens: opts.maxTokens || cfg.maxTokens })
    });
    if (!r.ok) {
      var e = ''; try { e = await r.text(); } catch (_) {}
      throw new Error('petabyte fallback HTTP ' + r.status + ' ' + e);
    }
    var b = await r.json();
    return { source: 'petabyte', model: b.model || opts.model || cfg.model, text: b.text || b.output || '', meta: b };
  }

  // The one call a site makes. Tries the visitor's GPU, falls back to Petabyte's API.
  async function infer(promptOrOpts, maybeOpts) {
    var prompt, opts;
    if (typeof promptOrOpts === 'string') { prompt = promptOrOpts; opts = maybeOpts || {}; }
    else { opts = promptOrOpts || {}; prompt = opts.prompt; }
    if (!prompt) throw new Error('infer: prompt required');
    var allow = (opts.allowOnDevice != null ? opts.allowOnDevice : cfg.allowOnDevice);
    if (allow) {
      try {
        var caps = await capabilities();
        if (caps.webgpu) { return await _onDevice(prompt, opts); }
      } catch (e) {
        if (opts.onFallback) { try { opts.onFallback(e); } catch (_) {} }
        // fall through to the paid fallback
      }
    }
    return await _fallback(prompt, opts);
  }

  global.PetabyteEdge = {
    configure: configure,
    capabilities: capabilities,
    infer: infer,
    version: '0.1.0-prototype'
  };
})(typeof window !== 'undefined' ? window : this);

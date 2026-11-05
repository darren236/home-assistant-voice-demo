// Bedside Voice Android port of the pinned OpenMOSS CodecStreamingDecodeSession.
// Apache-2.0; see repository LICENSE and NOTICE and the project provenance record.
package com.openmoss.ttsnano.onnxruntime

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OnnxTensorLike
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.Closeable
import java.io.File
import java.nio.FloatBuffer
import java.nio.IntBuffer
import org.json.JSONArray
import org.json.JSONObject

class StreamingCodec(
    private val env: OrtEnvironment,
    directory: File,
    meta: JSONObject,
    options: OrtSession.SessionOptions,
) : Closeable {
    private data class Binding(val input: String, val output: String,
                               val shape: LongArray, val floating: Boolean, val fill: Int = 0)
    private val session = env.createSession(File(directory,
        meta.getJSONObject("files").getString("decode_step")).absolutePath, options)
    private val bindings = ArrayList<Binding>()
    private val initial = ArrayList<OnnxTensor>()
    private var state = linkedMapOf<String, OnnxTensorLike>()
    private var previous: OrtSession.Result? = null
    private val quantizers = meta.getJSONObject("codec_config").getInt("num_quantizers")

    init {
        val streaming = meta.getJSONObject("streaming_decode")
        val offsets = streaming.getJSONArray("transformer_offsets")
        for (i in 0 until offsets.length()) {
            val spec = offsets.getJSONObject(i)
            bindings += Binding(spec.getString("input_name"), spec.getString("output_name"),
                                shape(spec.getJSONArray("shape")), false)
        }
        val caches = streaming.getJSONArray("attention_caches")
        for (i in 0 until caches.length()) {
            val spec = caches.getJSONObject(i)
            for (prefix in listOf("offset", "cached_keys", "cached_values", "cached_positions")) {
                val shapeName = when (prefix) {
                    "offset" -> "offset_shape"
                    "cached_positions" -> "positions_shape"
                    else -> "cache_shape"
                }
                bindings += Binding(spec.getString("${prefix}_input_name"),
                    spec.getString("${prefix}_output_name"), shape(spec.getJSONArray(shapeName)),
                    prefix == "cached_keys" || prefix == "cached_values",
                    if (prefix == "cached_positions") -1 else 0)
            }
        }
    }

    fun reset() {
        clear()
        try {
            for (binding in bindings) {
                val count = binding.shape.fold(1L) { a, b -> a * b }.toInt()
                val tensor = if (binding.floating) OnnxTensor.createTensor(env,
                    FloatBuffer.wrap(FloatArray(count)), binding.shape)
                else OnnxTensor.createTensor(env, IntBuffer.wrap(IntArray(count) { binding.fill }), binding.shape)
                initial += tensor
                state[binding.input] = tensor
            }
        } catch (error: Throwable) { clear(); throw error }
    }

    fun decode(frames: List<IntArray>): FloatArray {
        if (frames.isEmpty()) return FloatArray(0)
        val flat = IntArray(frames.size * quantizers)
        for (i in frames.indices) for (q in 0 until quantizers) flat[i * quantizers + q] = frames[i][q]
        OnnxTensor.createTensor(env, IntBuffer.wrap(flat),
            longArrayOf(1, frames.size.toLong(), quantizers.toLong())).use { codes ->
            OnnxTensor.createTensor(env, IntBuffer.wrap(intArrayOf(frames.size)), longArrayOf(1)).use { lengths ->
                val feeds = linkedMapOf<String, OnnxTensorLike>("audio_codes" to codes, "audio_code_lengths" to lengths)
                feeds.putAll(state)
                val result = session.run(feeds)
                try {
                    val next = linkedMapOf<String, OnnxTensorLike>()
                    for (binding in bindings) next[binding.input] = result.get(binding.output).get() as OnnxTensor
                    val raw = (result.get("audio").get() as OnnxTensor).value as Array<*>
                    val channels = (raw[0] as Array<*>).map { it as FloatArray }
                    val n = (result.get("audio_lengths").get() as OnnxTensor).intBuffer.get(0)
                        .coerceAtMost(channels.minOf { it.size })
                    val mono = FloatArray(n) { index ->
                        channels.sumOf { it[index].toDouble() }.toFloat() / channels.size
                    }
                    previous?.close()
                    initial.forEach { it.close() }; initial.clear()
                    state = next
                    previous = result
                    return mono
                } catch (error: Throwable) { result.close(); throw error }
            }
        }
    }

    fun clear() {
        state.clear()
        previous?.close(); previous = null
        initial.forEach { it.close() }; initial.clear()
    }

    override fun close() { clear(); session.close() }

    private fun shape(values: JSONArray) = LongArray(values.length()) { values.getLong(it) }
}

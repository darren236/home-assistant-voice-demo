package com.darren236.bedsidevoice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.openmoss.ttsnano.onnxruntime.MossOnnxDemoEngine
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.File
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.zip.ZipFile
import kotlin.math.roundToInt
import org.json.JSONObject

/** Loopback-only PCM streamer. Host tokenization and an SSH local forward supply requests. */
class PhoneSpeechService : Service() {
    @Volatile private var server: ServerSocket? = null
    @Volatile private var client: Socket? = null
    @Volatile private var destroyed = false
    private var worker: Thread? = null
    @Volatile private var ready = false
    private lateinit var fingerprint: String
    private val power by lazy { getSystemService(PowerManager::class.java) }

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("phone_speech", "Bedside speech", NotificationManager.IMPORTANCE_LOW))
        startForeground(2, Notification.Builder(this, "phone_speech")
            .setContentTitle("Bedside voice ready")
            .setContentText("Local MOSS speech synthesis")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now).setOngoing(true).build())
        worker = Thread({ runServer() }, "BedsideSpeech").also { it.start() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun runServer() {
        var retryMs = 1000L
        while (!destroyed && !Thread.currentThread().isInterrupted) {
            try {
                serveAttempt()
            } catch (_: InterruptedException) {
                break
            } catch (error: Exception) {
                if (!destroyed) Log.e("BedsideSpeech", "Speech service will retry", error)
            } finally {
                ready = false
                server = null
            }
            if (destroyed || Thread.currentThread().isInterrupted) break
            try { Thread.sleep(retryMs) } catch (_: InterruptedException) { break }
            retryMs = (retryMs * 2).coerceAtMost(30_000L)
        }
    }

    private fun checkRunning() {
        if (destroyed || Thread.currentThread().isInterrupted) throw InterruptedException()
    }

    private fun serveAttempt() {
        try {
            checkRunning()
            val external = getExternalFilesDir(null) ?: error("App storage unavailable")
            val fixtures = JSONObject(File(external, "fixtures.json").readText())
            val rows = fixtures.getJSONArray("prompt_audio_codes")
            val codes = List(rows.length()) { i -> rows.getJSONArray(i).let { row -> IntArray(row.length()) { j -> row.getInt(j) } } }
            val secret = File(filesDir, "auth.token").readText().trim().toByteArray()
            require(secret.size >= 32) { "Speech token missing" }
            val modelRoot = File(external, "models-int8")
            val engineIdentity = assets.open("bedside-render-identity.txt").bufferedReader().use { it.readText().trim() }
            val runtimeIdentity = ZipFile(applicationInfo.sourceDir).use { apk ->
                apk.entries().asSequence().filter { it.name.startsWith("lib/arm64-v8a/") && it.name.endsWith(".so") }
                    .sortedBy { it.name }.joinToString("") { entry ->
                        val digest = MessageDigest.getInstance("SHA-256")
                        apk.getInputStream(entry).use { stream ->
                            val buffer = ByteArray(65536)
                            while (true) {
                                checkRunning()
                                val count = stream.read(buffer)
                                if (count < 0) break
                                digest.update(buffer, 0, count)
                            }
                        }
                        entry.name + ":" + digest.digest().joinToString("") { "%02x".format(it) } + "\n"
                    }
            }
            val material = modelRoot.walkTopDown().filter { it.isFile }.sortedBy { it.relativeTo(modelRoot).path }
                .joinToString("") { "${it.relativeTo(modelRoot).path}:${sha256(it)}\n" } +
                "fixtures:${sha256(File(external, "fixtures.json"))}\nengine:$engineIdentity\nruntime:$runtimeIdentity\n"
            fingerprint = MessageDigest.getInstance("SHA-256").digest(material.toByteArray()).joinToString("") { "%02x".format(it) }
            checkRunning()
            MossOnnxDemoEngine(modelRoot, cacheDir, 3, codes, true, 2).use { engine ->
                ServerSocket().use { listener ->
                    synchronized(this) {
                        checkRunning()
                        server = listener
                        listener.bind(InetSocketAddress(InetAddress.getByName("127.0.0.1"), 12882), 4)
                    }
                    ready = true
                    Log.i("BedsideSpeech", "Loopback TTS ready")
                    while (!destroyed && !Thread.currentThread().isInterrupted) {
                        listener.accept().use {
                            client = it
                            try { checkRunning(); handle(it, engine, secret) }
                            finally { client = null }
                        }
                    }
                }
            }
        } finally {
            ready = false
        }
    }

    private fun handle(socket: Socket, engine: MossOnnxDemoEngine, secret: ByteArray) {
        socket.soTimeout = 5000
        val input = BufferedInputStream(socket.getInputStream())
        val output = BufferedOutputStream(socket.getOutputStream())
        var responseStarted = false
        try {
            val request = readLine(input)
            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = readLine(input)
                if (line.isEmpty()) break
                val colon = line.indexOf(':')
                require(colon > 0) { "Bad HTTP header" }
                headers[line.substring(0, colon).lowercase()] = line.substring(colon + 1).trim()
            }
            val provided = headers["authorization"]?.removePrefix("Bearer ")?.toByteArray() ?: byteArrayOf()
            if (!MessageDigest.isEqual(secret, provided)) {
                respond(output, 403, "Forbidden")
                return
            }
            if (request.startsWith("GET /health ")) {
                val battery = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
                val status = JSONObject().put("status", "ready").put("fingerprint", fingerprint)
                    .put("thermal_status", power.currentThermalStatus)
                    .put("battery_c", (battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1) / 10.0)
                    .put("charging", (battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) != 0)
                respond(output, 200, status.toString())
                return
            }
            if (!request.startsWith("POST /synthesize ")) {
                respond(output, 404, "Not found")
                return
            }
            val length = headers["content-length"]?.toIntOrNull() ?: 0
            require(length in 1..4096) { "Bad request size" }
            val body = ByteArray(length)
            var offset = 0
            while (offset < length) {
                val n = input.read(body, offset, length - offset)
                if (n < 0) error("Truncated request")
                offset += n
            }
            val requestBody = JSONObject(String(body, Charsets.UTF_8))
            val ids = requestBody.getJSONArray("token_ids")
            require(ids.length() in 1..75) { "Unsupported text length" }
            val tokens = IntArray(ids.length()) { ids.getInt(it) }
            val seed = requestBody.optLong("seed", 7411L)
            val thermal = power.currentThermalStatus
            if (thermal >= PowerManager.THERMAL_STATUS_SEVERE) {
                respond(output, 503, "Phone cooling")
                return
            }
            val wake = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "bedside:speech")
            wake.acquire(15 * 60 * 1000L)
            try {
                output.write("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\nX-Audio-Rate: 48000\r\nX-Bedside-Model: $fingerprint\r\nConnection: close\r\n\r\n".toByteArray())
                output.flush()
                responseStarted = true
                val started = System.nanoTime()
                var sent = 0
                val result = engine.synthesize(tokens, File(cacheDir, "unused.wav"), seed = seed,
                    writeWav = false, onPcm = { samples ->
                        checkRunning()
                        val pcm = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
                        for (sample in samples) pcm.putShort((sample.coerceIn(-1f, 1f) * 32767).roundToInt().toShort())
                        val chunk = pcm.array()
                        output.write("${chunk.size.toString(16)}\r\n".toByteArray())
                        output.write(chunk)
                        output.write("\r\n".toByteArray())
                        output.flush()
                        sent += chunk.size
                    })
                if (result.hitFrameLimit || sent == 0) error("Speech incomplete")
                output.write("0\r\n\r\n".toByteArray())
                output.flush()
                Log.i("BedsideSpeech", "bytes=$sent first_pcm_ms=${result.firstPcmMs} total_ms=${(System.nanoTime()-started)/1000000}")
            } finally { if (wake.isHeld) wake.release() }
        } catch (error: Throwable) {
            Log.w("BedsideSpeech", "Request failed", error)
            if (!responseStarted && !destroyed) {
                try { respond(output, 500, "Speech failed") } catch (_: Exception) { }
            }
        }
    }

    private fun readLine(input: BufferedInputStream): String {
        val bytes = ArrayList<Byte>()
        while (bytes.size < 4096) {
            val value = input.read()
            if (value < 0) error("Closed request")
            if (value == 10) {
                if (bytes.lastOrNull() == 13.toByte()) bytes.removeAt(bytes.lastIndex)
                return String(bytes.toByteArray(), Charsets.UTF_8)
            }
            bytes += value.toByte()
        }
        error("Request header too long")
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { stream ->
            val buffer = ByteArray(65536)
            while (true) {
                checkRunning()
                val count = stream.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun respond(output: BufferedOutputStream, status: Int, message: String) {
        val body = message.toByteArray()
        output.write("HTTP/1.1 $status\r\nContent-Type: text/plain\r\nContent-Length: ${body.size}\r\nConnection: close\r\n\r\n".toByteArray())
        output.write(body)
        output.flush()
    }

    override fun onDestroy() {
        synchronized(this) {
            destroyed = true
            server?.close()
            client?.close()
        }
        worker?.interrupt()
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}

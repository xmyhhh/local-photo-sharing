package org.example.localphotoandroid

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Environment
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.lifecycle.MutableLiveData
import com.chaquo.python.Python
import com.chaquo.python.PyObject
import com.chaquo.python.PyException
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.net.Inet4Address
import java.time.LocalDateTime
import kotlin.concurrent.thread

data class ServiceState(
    val starting: Boolean = false,
    val running: Boolean = false,
    val localUrl: String = "",
    val lanUrl: String = "",
    val message: String? = null,
    val error: String? = null,
) {
    companion object {
        fun stopped() = ServiceState(message = "服务已停止")
        fun starting() = ServiceState(starting = true, message = "正在初始化 Python 服务")
    }
}

class PhotoShareService : Service() {
    private var worker: Thread? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification())
        if (worker?.isAlive != true) {
            publish(ServiceState.starting())
            worker = thread(name = "photo-share-python") {
                runPythonServer()
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        runCatching {
            if (Python.isStarted()) {
                Python.getInstance().getModule("android_shell").callAttr("stop_server")
            }
        }
        publish(ServiceState.stopped())
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun runPythonServer() {
        try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(this))
            }
            val python = Python.getInstance()
            val module = python.getModule("android_shell")
            val appDir = File(filesDir, "photo_share").absolutePath
            val defaultPhotoDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES)
                ?: File(filesDir, "Pictures")
            defaultPhotoDir.mkdirs()
            val result = module.callAttr(
                "start_server",
                applicationContext,
                appDir,
                defaultPhotoDir.absolutePath,
            )
            val port = pyMapValue(result, "port")?.toString()?.toIntOrNull() ?: 8000
            val localUrl = "http://127.0.0.1:$port"
            val lanUrl = lanAddress()?.let { "http://$it:$port" }.orEmpty()
            publish(
                ServiceState(
                    running = true,
                    localUrl = localUrl,
                    lanUrl = lanUrl,
                    message = if (lanUrl.isBlank()) "服务已启动，但暂未识别到局域网 IPv4 地址。" else null,
                ),
            )
            module.callAttr("serve_forever")
        } catch (error: PyException) {
            appendServiceLog(error.stackTraceToString())
            publish(ServiceState(error = error.stackTraceToString()))
            stopSelf()
        } catch (error: Throwable) {
            appendServiceLog(error.stackTraceToString())
            publish(ServiceState(error = error.message ?: error.toString()))
            stopSelf()
        }
    }

    private fun appendServiceLog(text: String) {
        runCatching {
            val logFile = File(File(filesDir, "photo_share"), "android_service.log")
            logFile.parentFile?.mkdirs()
            logFile.appendText("${LocalDateTime.now()} ERROR AndroidService\n$text\n")
        }
    }

    private fun lanAddress(): String? {
        val connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = connectivity.activeNetwork ?: return wifiIpAddressFallback()
        val linkProperties: LinkProperties = connectivity.getLinkProperties(network) ?: return wifiIpAddressFallback()
        return linkProperties.linkAddresses
            .map { it.address }
            .filterIsInstance<Inet4Address>()
            .firstOrNull { !it.isLoopbackAddress }
            ?.hostAddress
            ?: wifiIpAddressFallback()
    }

    private fun pyMapValue(map: PyObject, key: String): PyObject? {
        return map.asMap().entries.firstOrNull { it.key.toString() == key }?.value
    }

    private fun wifiIpAddressFallback(): String? {
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return null
        val ip = wifi.connectionInfo?.ipAddress ?: return null
        if (ip == 0) return null
        return listOf(
            ip and 0xff,
            ip shr 8 and 0xff,
            ip shr 16 and 0xff,
            ip shr 24 and 0xff,
        ).joinToString(".")
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.app_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        val manager = getSystemService(NotificationManager::class.java)
        manager?.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.service_notification_title))
            .setContentText(getString(R.string.service_notification_text))
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "photo_share_service"
        private const val NOTIFICATION_ID = 2308
        val state = MutableLiveData(ServiceState.stopped())

        fun publish(nextState: ServiceState) {
            state.postValue(nextState)
        }
    }
}

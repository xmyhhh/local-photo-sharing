package org.example.localphotoandroid

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import org.example.localphotoandroid.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { startPhotoShareService() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        applySystemInsets()
        bindActions()
        PhotoShareService.state.observe(this) { renderState(it) }
    }

    private fun applySystemInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val cutout = insets.getInsets(WindowInsetsCompat.Type.displayCutout())
            binding.header.updatePadding(
                left = 24.dp + maxOf(bars.left, cutout.left),
                top = 26.dp + maxOf(bars.top, cutout.top),
                right = 24.dp + maxOf(bars.right, cutout.right),
            )
            binding.content.updatePadding(
                left = 24.dp + maxOf(bars.left, cutout.left),
                right = 24.dp + maxOf(bars.right, cutout.right),
                bottom = 24.dp + maxOf(bars.bottom, cutout.bottom),
            )
            insets
        }
    }

    private fun bindActions() {
        binding.startStopButton.setOnClickListener {
            if (PhotoShareService.state.value?.running == true) {
                stopService(Intent(this, PhotoShareService::class.java))
                PhotoShareService.publish(ServiceState.stopped())
            } else {
                requestNotificationPermissionThenStart()
            }
        }
        binding.copyLanButton.setOnClickListener {
            val lanUrl = PhotoShareService.state.value?.lanUrl.orEmpty()
            if (lanUrl.isBlank()) return@setOnClickListener
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText(getString(R.string.lan_url), lanUrl))
            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
        }
        binding.openLocalButton.setOnClickListener {
            val localUrl = PhotoShareService.state.value?.localUrl.orEmpty()
            if (localUrl.isBlank()) return@setOnClickListener
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(localUrl)))
        }
    }

    private fun requestNotificationPermissionThenStart() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            startPhotoShareService()
        }
    }

    private fun startPhotoShareService() {
        ContextCompat.startForegroundService(this, Intent(this, PhotoShareService::class.java))
    }

    private fun renderState(state: ServiceState) {
        binding.statusText.text = when {
            state.running -> getString(R.string.service_running)
            state.starting -> getString(R.string.service_starting)
            state.error != null -> getString(R.string.service_error)
            else -> getString(R.string.service_stopped)
        }
        binding.messageText.text = state.error ?: state.message ?: if (state.running) {
            getString(R.string.service_running_hint)
        } else {
            getString(R.string.service_ready_hint)
        }
        binding.localUrlText.text = state.localUrl.ifBlank { getString(R.string.url_placeholder) }
        binding.lanUrlText.text = state.lanUrl.ifBlank { getString(R.string.url_placeholder) }
        binding.startStopButton.text = if (state.running || state.starting) {
            getString(R.string.stop_service)
        } else {
            getString(R.string.start_service)
        }
        binding.copyLanButton.isEnabled = state.lanUrl.isNotBlank()
        binding.openLocalButton.isEnabled = state.localUrl.isNotBlank()
    }

    private val Int.dp: Int
        get() = (this * resources.displayMetrics.density).toInt()
}

package org.example.localphotoandroid

import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import org.example.localphotoandroid.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.logButton.setOnClickListener {
            val message = "Button pressed from Android platform app"
            Log.i("LocalPhotoAndroid", message)
            binding.statusText.text = message
        }
    }
}

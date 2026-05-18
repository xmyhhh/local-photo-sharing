plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

import java.util.Properties

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.isFile) {
        file.inputStream().use(::load)
    }
}
val chaquopyBuildPython = localProperties.getProperty("chaquopy.buildPython")
    ?: providers.environmentVariable("CHAQUOPY_BUILD_PYTHON").orNull

val generatedPythonDir = layout.buildDirectory.dir("generated/python")
val syncPythonSources by tasks.registering(Sync::class) {
    into(generatedPythonDir)
    from("../../../core") {
        into("core")
    }
    from("../../../core/static") {
        into("static")
    }
    from("../../../plugins") {
        into("plugins")
    }
}

android {
    namespace = "org.example.localphotoandroid"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.example.localphotoandroid"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

tasks.named("preBuild") {
    dependsOn(syncPythonSources)
}
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncPythonSources)
}

chaquopy {
    defaultConfig {
        version = "3.13"
        if (!chaquopyBuildPython.isNullOrBlank()) {
            buildPython(chaquopyBuildPython)
        }
        extractPackages("*")
        pip {
            install("Flask==3.0.3")
            install("Werkzeug==3.0.3")
            install("Pillow==11.0.0")
            install("numpy")
            install("piexif==1.1.3")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(generatedPythonDir)
        }
    }
}

dependencies {
    implementation("androidx.activity:activity-ktx:1.10.0")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.2.0")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}

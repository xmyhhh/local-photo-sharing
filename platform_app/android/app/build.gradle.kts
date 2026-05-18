plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val generatedPythonDir = layout.buildDirectory.dir("generated/python")
val syncPythonSources by tasks.registering(Sync::class) {
    into(generatedPythonDir)
    from("src/main/python")
    from("../../../core") {
        into("core")
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

    flavorDimensions += "pyVersion"
    productFlavors {
        create("py310") { dimension = "pyVersion" }
        create("py311") { dimension = "pyVersion" }
        create("py312") { dimension = "pyVersion" }
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

chaquopy {
    defaultConfig {
        version = "3.11"
        extractPackages("*")
        pip {
            install("Flask==3.0.3")
            install("Werkzeug==3.0.3")
            install("Pillow==10.4.0")
            install("numpy==1.26.4")
            install("piexif==1.1.3")
        }
    }
    productFlavors {
        getByName("py310") { version = "3.10" }
        getByName("py311") { version = "3.11" }
        getByName("py312") { version = "3.12" }
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

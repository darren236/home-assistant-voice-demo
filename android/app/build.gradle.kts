import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.darren236.bedsidevoice"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.darren236.bedsidevoice"
        minSdk = 29
        targetSdk = 33
        versionCode = 1
        versionName = "0.1"
        ndk { abiFilters += "arm64-v8a" }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
    sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/bedsideAssets"))
    sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/bedsideLegal"))
}

val copyProjectNotices by tasks.registering(Copy::class) {
    from(rootProject.file("../LICENSE"), rootProject.file("../NOTICE"))
    into(layout.buildDirectory.dir("generated/bedsideLegal/licenses"))
}

val writeRenderIdentity by tasks.registering {
    val sources = fileTree("src/main/java/com/openmoss") { include("**/*.kt") }.files +
        file("src/main/java/com/darren236/bedsidevoice/PhoneSpeechService.kt")
    val output = layout.buildDirectory.file("generated/bedsideAssets/bedside-render-identity.txt")
    inputs.files(sources)
    outputs.file(output)
    doLast {
        val material = sources.sortedBy { it.path }.joinToString("") {
            it.relativeTo(projectDir).path + ":" + MessageDigest.getInstance("SHA-256")
                .digest(it.readBytes()).joinToString("") { byte -> "%02x".format(byte) } + "\n"
        }
        output.get().asFile.apply {
            parentFile.mkdirs()
            writeText(MessageDigest.getInstance("SHA-256").digest(material.toByteArray())
                .joinToString("") { "%02x".format(it) })
        }
    }
}
tasks.named("preBuild").configure { dependsOn(writeRenderIdentity, copyProjectNotices) }


dependencies { implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0") }

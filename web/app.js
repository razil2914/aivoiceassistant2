/* ==============================================================
   J.A.R.V.I.S  HUD  —  Babylon.js 3D Orb + Frontend Logic
   Dark sphere with neon cyan Fresnel rim + flowing light streaks
   Voice-reactive: amplitude drives glow, streaks, particles
   ============================================================== */

// ── State ──
var micActive = false, camActive = false, speaking = false, amplitude = 0;
var msgCount = 0, ready = false;

// ── DOM refs (set in DOMContentLoaded) ──
var $q = function(s) { return document.querySelector(s); };
var transcriptLog, chatInput, micBtn, micLabel, statusText, orbCanvas;
var camToggle, setupOverlay, sysTimeEl, msgCountEl;

// ── Babylon globals ──
var engine, scene, cam, glowLayer;
var orbMesh, orbMaterial;
var smoothAmp = 0, smoothSpeak = 0, orbTime = 0;
var streakMeshes = [];
var particleSys;
var streamEl = null, streamTag = '';


// ──────────────────────────────────────────────────────────
//  Init Babylon.js 3D Orb
// ──────────────────────────────────────────────────────────
function initOrb() {
    // Force canvas to match container size before engine creation
    var container = orbCanvas.parentElement;
    var w = container.clientWidth  || container.offsetWidth  || 400;
    var h = container.clientHeight || container.offsetHeight || 400;
    orbCanvas.width  = w;
    orbCanvas.height = h;

    engine = new BABYLON.Engine(orbCanvas, true, {
        preserveDrawingBuffer: true,
        stencil: true,
        antialias: true,
        adaptToDeviceRatio: true
    });

    scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(0, 0, 0, 0);
    scene.ambientColor = new BABYLON.Color3(0.02, 0.02, 0.05);

    // Fixed camera — no user interaction
    cam = new BABYLON.ArcRotateCamera('cam', -Math.PI / 2, Math.PI / 2, 4.5, BABYLON.Vector3.Zero(), scene);
    cam.lowerRadiusLimit = 4.5;
    cam.upperRadiusLimit = 4.5;

    // ── Glow layer ──
    glowLayer = new BABYLON.GlowLayer('glow', scene, {
        mainTextureSamples: 4,
        blurKernelSize: 64
    });
    glowLayer.intensity = 0.8;

    // ── Dark sphere body ──
    orbMesh = BABYLON.MeshBuilder.CreateSphere('orb', { diameter: 2, segments: 64 }, scene);
    orbMaterial = new BABYLON.StandardMaterial('orbMat', scene);
    orbMaterial.diffuseColor = new BABYLON.Color3(0.01, 0.015, 0.03);
    orbMaterial.specularColor = new BABYLON.Color3(0.05, 0.15, 0.3);
    orbMaterial.specularPower = 64;
    orbMaterial.emissiveColor = new BABYLON.Color3(0.005, 0.01, 0.025);

    // Neon cyan Fresnel rim
    orbMaterial.emissiveFresnelParameters = new BABYLON.FresnelParameters();
    orbMaterial.emissiveFresnelParameters.bias = 0.1;
    orbMaterial.emissiveFresnelParameters.power = 3;
    orbMaterial.emissiveFresnelParameters.leftColor = new BABYLON.Color3(0, 0.7, 1);
    orbMaterial.emissiveFresnelParameters.rightColor = new BABYLON.Color3(0, 0.02, 0.05);

    orbMaterial.opacityFresnelParameters = new BABYLON.FresnelParameters();
    orbMaterial.opacityFresnelParameters.bias = 0.95;
    orbMaterial.opacityFresnelParameters.power = 1.5;
    orbMaterial.opacityFresnelParameters.leftColor = BABYLON.Color3.White();
    orbMaterial.opacityFresnelParameters.rightColor = BABYLON.Color3.White();

    orbMesh.material = orbMaterial;
    glowLayer.addIncludedOnlyMesh(orbMesh);

    // ── Light streaks ──
    createStreaks(12);

    // ── Lights ──
    var center = new BABYLON.PointLight('center', BABYLON.Vector3.Zero(), scene);
    center.diffuse = new BABYLON.Color3(0, 0.4, 0.8);
    center.specular = new BABYLON.Color3(0, 0.5, 1);
    center.intensity = 0.3;
    center.range = 6;

    var hemi = new BABYLON.HemisphericLight('hemi', new BABYLON.Vector3(0, 1, 0), scene);
    hemi.diffuse = new BABYLON.Color3(0.01, 0.03, 0.06);
    hemi.specular = new BABYLON.Color3(0, 0.1, 0.2);
    hemi.intensity = 0.4;

    // ── Floating particles ──
    createParticles();

    // ── Render loop ──
    engine.runRenderLoop(function() {
        var dt = engine.getDeltaTime() / 1000;
        orbTime += dt;
        updateVoiceSmoothing(dt);
        updateOrbEffects(dt);
        scene.render();
    });
}


// ──────────────────────────────────────────────────────────
//  Light streaks — glowing tubes on the sphere surface
// ──────────────────────────────────────────────────────────
function createStreaks(count) {
    for (var i = 0; i < count; i++) {
        var points = [];
        var segments = 40;
        var latOffset = (Math.random() - 0.5) * Math.PI * 0.7;
        var lonStart = Math.random() * Math.PI * 2;
        var arcLen = 0.6 + Math.random() * 1.2;

        for (var j = 0; j <= segments; j++) {
            var t = j / segments;
            var lon = lonStart + t * arcLen;
            var lat = latOffset + Math.sin(t * Math.PI) * 0.2;
            var r = 1.02 + Math.sin(t * Math.PI) * 0.03;
            points.push(new BABYLON.Vector3(
                Math.cos(lon) * Math.cos(lat) * r,
                Math.sin(lat) * r,
                Math.sin(lon) * Math.cos(lat) * r
            ));
        }

        var tube = BABYLON.MeshBuilder.CreateTube('streak' + i, {
            path: points,
            radius: 0.005 + Math.random() * 0.012,
            tessellation: 8,
            updatable: true
        }, scene);

        var mat = new BABYLON.StandardMaterial('streakMat' + i, scene);
        mat.emissiveColor = new BABYLON.Color3(0.1, 0.7, 1);
        mat.diffuseColor = new BABYLON.Color3(0, 0, 0);
        mat.specularColor = new BABYLON.Color3(0, 0, 0);
        mat.alpha = 0.4 + Math.random() * 0.4;
        mat.backFaceCulling = false;
        tube.material = mat;
        glowLayer.addIncludedOnlyMesh(tube);

        streakMeshes.push({
            mesh: tube,
            mat: mat,
            latOffset: latOffset,
            lonStart: lonStart,
            arcLen: arcLen,
            speed: 0.3 + Math.random() * 0.6,
            phase: Math.random() * Math.PI * 2,
            baseBrightness: 0.3 + Math.random() * 0.7,
            baseAlpha: 0.4 + Math.random() * 0.4,
            segments: segments
        });
    }
}


// ──────────────────────────────────────────────────────────
//  Particles — floating cyan embers
// ──────────────────────────────────────────────────────────
function createParticles() {
    particleSys = new BABYLON.ParticleSystem('particles', 200, scene);

    var texSize = 32;
    var dynTex = new BABYLON.DynamicTexture('partTex', texSize, scene, false);
    var texCtx = dynTex.getContext();
    var grad = texCtx.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0, 'rgba(150, 230, 255, 1)');
    grad.addColorStop(0.5, 'rgba(0, 150, 255, 0.5)');
    grad.addColorStop(1, 'rgba(0, 50, 150, 0)');
    texCtx.fillStyle = grad;
    texCtx.fillRect(0, 0, texSize, texSize);
    dynTex.update();

    particleSys.particleTexture = dynTex;
    particleSys.emitter = BABYLON.Vector3.Zero();
    particleSys.createSphereEmitter(1.3);

    particleSys.minLifeTime = 2;
    particleSys.maxLifeTime = 5;
    particleSys.minSize = 0.01;
    particleSys.maxSize = 0.04;
    particleSys.emitRate = 30;

    particleSys.color1 = new BABYLON.Color4(0.3, 0.8, 1, 0.6);
    particleSys.color2 = new BABYLON.Color4(0, 0.5, 1, 0.3);
    particleSys.colorDead = new BABYLON.Color4(0, 0.1, 0.3, 0);

    particleSys.minEmitPower = 0.02;
    particleSys.maxEmitPower = 0.08;
    particleSys.blendMode = BABYLON.ParticleSystem.BLENDMODE_ADD;

    particleSys.start();
}


// ──────────────────────────────────────────────────────────
//  Voice smoothing — fast attack / slow release
// ──────────────────────────────────────────────────────────
function updateVoiceSmoothing(dt) {
    var target = amplitude;
    if (target > smoothAmp) {
        smoothAmp += (target - smoothAmp) * Math.min(1, dt * 15);
    } else {
        smoothAmp += (target - smoothAmp) * Math.min(1, dt * 4);
    }
    smoothSpeak += ((speaking ? 1 : 0) - smoothSpeak) * Math.min(1, dt * 6);
}


// ──────────────────────────────────────────────────────────
//  Per-frame voice-reactive updates
// ──────────────────────────────────────────────────────────
function updateOrbEffects(dt) {
    var amp = smoothAmp;
    var spk = smoothSpeak;

    // Fresnel intensity reacts to voice
    orbMaterial.emissiveFresnelParameters.power = Math.max(0.5, 3 - amp * 4 - spk * 2);
    orbMaterial.emissiveFresnelParameters.leftColor = new BABYLON.Color3(0, 0.55 + amp * 0.45, 0.85 + amp * 0.15);
    orbMaterial.emissiveColor = new BABYLON.Color3(0.005 + amp * 0.02, 0.01 + amp * 0.06, 0.025 + amp * 0.08);

    // Glow intensity
    glowLayer.intensity = 0.6 + amp * 1.2 + spk * 0.5;

    // Orb scale pulse
    var pulse = 1 + Math.sin(orbTime * 2) * 0.01 + amp * 0.06;
    orbMesh.scaling.set(pulse, pulse, pulse);

    // Animate streaks
    var speedMult = 1 + amp * 4 + spk * 2;
    for (var i = 0; i < streakMeshes.length; i++) {
        var s = streakMeshes[i];
        s.lonStart += s.speed * speedMult * dt;

        var newPoints = [];
        for (var j = 0; j <= s.segments; j++) {
            var t = j / s.segments;
            var lon = s.lonStart + t * s.arcLen;
            var lat = s.latOffset + Math.sin(t * Math.PI + orbTime * 0.5) * 0.2;
            var r = 1.02 + Math.sin(t * Math.PI) * 0.03 + amp * 0.02;
            newPoints.push(new BABYLON.Vector3(
                Math.cos(lon) * Math.cos(lat) * r,
                Math.sin(lat) * r,
                Math.sin(lon) * Math.cos(lat) * r
            ));
        }

        s.mesh = BABYLON.MeshBuilder.CreateTube(null, {
            path: newPoints,
            radius: (0.005 + amp * 0.015) * (s.baseBrightness * 0.5 + 0.5),
            tessellation: 8,
            instance: s.mesh
        });

        var streakPulse = 0.5 + 0.5 * Math.sin(orbTime * 2.5 + s.phase);
        var streakAlpha = s.baseAlpha * (0.4 + amp * 0.6 + spk * 0.3) * (0.6 + streakPulse * 0.4);
        s.mat.alpha = Math.min(1, streakAlpha);
        var bright = s.baseBrightness * (0.5 + amp * 1.0 + spk * 0.5);
        s.mat.emissiveColor = new BABYLON.Color3(0.1 * bright, 0.6 * bright, 1.0 * bright);
    }

    // Particles react
    if (particleSys) {
        particleSys.emitRate = 30 + amp * 150;
        particleSys.minEmitPower = 0.02 + amp * 0.1;
        particleSys.maxEmitPower = 0.08 + amp * 0.3;
        particleSys.maxSize = 0.04 + amp * 0.06;
    }

    // Subtle auto-rotation
    cam.alpha += dt * 0.08 * (1 + amp * 2);
}


// ──────────────────────────────────────────────────────────
//  Clock
// ──────────────────────────────────────────────────────────
function updateClock() {
    var now = new Date();
    sysTimeEl.textContent =
        String(now.getHours()).padStart(2, '0') + ':' +
        String(now.getMinutes()).padStart(2, '0') + ':' +
        String(now.getSeconds()).padStart(2, '0');
}


// ──────────────────────────────────────────────────────────
//  Tab switching
// ──────────────────────────────────────────────────────────
function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
    var activeTab = document.querySelector('.tab[data-tab="' + tabName + '"]');
    if (activeTab) activeTab.classList.add('active');

    document.querySelectorAll('.tab-page').forEach(function(p) { p.classList.remove('active'); });
    var page = document.getElementById('page-' + tabName);
    if (page) page.classList.add('active');

    if (tabName === 'dashboard' && engine) {
        setTimeout(function() { engine.resize(); }, 50);
        setTimeout(function() { engine.resize(); }, 200);
    }
}


// ──────────────────────────────────────────────────────────
//  DOMContentLoaded — Init everything
// ──────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', function() {
    transcriptLog = $q('#transcriptLog');
    chatInput     = $q('#chatInput');
    micBtn        = $q('#micBtn');
    micLabel      = $q('#micLabel');
    statusText    = $q('#statusText');
    orbCanvas     = $q('#orbCanvas');
    camToggle     = $q('#camToggle');
    setupOverlay  = $q('#setupOverlay');
    sysTimeEl     = $q('#sysTime');
    msgCountEl    = $q('#msgCount');

    try {
        initOrb();
        engine.resize();
        setTimeout(function() { if (engine) engine.resize(); }, 50);
    } catch (e) {
        console.warn('[HUD] 3D orb init failed (WebGL unavailable?):', e.message);
    }

    updateClock();
    setInterval(updateClock, 1000);
    startMetricsPolling();

    chatInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') sendChat();
    });

    window.addEventListener('resize', function() {
        if (engine) engine.resize();
    });
    setTimeout(function() { if (engine) engine.resize(); }, 100);
    setTimeout(function() { if (engine) engine.resize(); }, 500);
    setTimeout(function() { if (engine) engine.resize(); }, 1500);

    // Tab switching
    document.querySelectorAll('.tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            var tabName = tab.getAttribute('data-tab');
            switchTab(tabName);
        });
    });

    waitForApi(function() {});
});


// ──────────────────────────────────────────────────────────
//  API Bridge helpers
// ──────────────────────────────────────────────────────────
function waitForApi(cb, maxWait) {
    maxWait = maxWait || 10000;
    var start = Date.now();
    var check = function() {
        if (window.pywebview && window.pywebview.api) {
            ready = true;
            cb();
        } else if (Date.now() - start < maxWait) {
            setTimeout(check, 100);
        }
    };
    check();
}

function sendChat() {
    var text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = '';
    appendMessage('You: ' + text, 'you');
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.send_chat(text);
    }
}


// ──────────────────────────────────────────────────────────
//  Metrics Polling
// ──────────────────────────────────────────────────────────
function startMetricsPolling() {
    setInterval(function() {
        if (!window.pywebview || !window.pywebview.api) return;

        window.pywebview.api.get_metrics().then(function(data) {
            if (!data) return;

            var cpuVal = $q('#cpuVal'), cpuBar = $q('#cpuBar'), cpuGlow = $q('#cpuGlow');
            if (cpuVal) cpuVal.textContent = data.cpu.toFixed(1) + '%';
            if (cpuBar) cpuBar.style.width = data.cpu + '%';
            if (cpuGlow) cpuGlow.style.width = data.cpu + '%';

            var ramVal = $q('#ramVal'), ramBar = $q('#ramBar'), ramGlow = $q('#ramGlow');
            if (ramVal) ramVal.textContent = data.mem_pct.toFixed(1) + '% (' + data.mem_used.toFixed(1) + ' GB)';
            if (ramBar) ramBar.style.width = data.mem_pct + '%';
            if (ramGlow) ramGlow.style.width = data.mem_pct + '%';

            var procList = $q('#procList');
            if (procList) {
                procList.innerHTML = '';
                (data.top_procs || []).forEach(function(proc) {
                    var row = document.createElement('div');
                    row.className = 'proc-row';
                    row.innerHTML =
                        '<span class="proc-name">' + escHtml(proc.name || 'unknown') + '</span>' +
                        '<span class="proc-cpu">' + (proc.cpu_percent || 0).toFixed(1) + '%</span>' +
                        '<span class="proc-mem">' + (proc.memory_percent || 0).toFixed(1) + '%</span>';
                    procList.appendChild(row);
                });
            }

            if (data.speaking !== speaking) {
                speaking = data.speaking;
                document.body.classList.toggle('speaking', speaking);
                updateStatusText();
            }
            if (data.mic_active !== micActive) {
                micActive = data.mic_active;
                updateMicUI();
            }
        }).catch(function() {});
    }, 800);
}


// ──────────────────────────────────────────────────────────
//  Public API — called from Python via evaluate_js()
// ──────────────────────────────────────────────────────────

function writeLog(text) {
    var tl = text.toLowerCase();
    var tag = 'sys';
    if (tl.startsWith('you:')) tag = 'you';
    else if (tl.startsWith('ai:')) tag = 'ai';
    appendMessage(text, tag);
}

function streamLog(text, tag) {
    if (tag !== streamTag || !streamEl) {
        streamEl = document.createElement('div');
        streamEl.className = 'msg msg-' + tag;
        transcriptLog.appendChild(streamEl);
        streamTag = tag;
    }
    streamEl.textContent += text;
    transcriptLog.scrollTop = transcriptLog.scrollHeight;
}

function streamEnd() {
    streamEl = null;
    streamTag = '';
}

function setAmplitude(val) {
    amplitude = val;
}

function setSpeaking(val) {
    speaking = val;
    document.body.classList.toggle('speaking', val);
    updateStatusText();
}

function setMicActive(val) {
    micActive = val;
    updateMicUI();
    updateStatusText();
}

function showSetupUI() {
    setupOverlay.style.display = 'flex';
}

function hideSetupUI() {
    setupOverlay.style.display = 'none';
}

function updateCameraFrame(base64Data) {
    var camFeed = $q('#camFeed'), camOffline = $q('#camOffline');
    if (base64Data) {
        camFeed.src = 'data:image/jpeg;base64,' + base64Data;
        camFeed.style.display = 'block';
        camOffline.style.display = 'none';
    } else {
        camFeed.style.display = 'none';
        camOffline.style.display = 'flex';
    }
}


// ──────────────────────────────────────────────────────────
//  UI Interactions
// ──────────────────────────────────────────────────────────

function toggleMic() {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.toggle_mic();
}

function toggleCam() {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.toggle_video();
    camActive = !camActive;
    camToggle.classList.toggle('active', camActive);
    if (!camActive) updateCameraFrame(null);
}

function saveApiKey() {
    var key = $q('#apiKeyInput').value.trim();
    if (!key) return;
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.save_api_key(key);
        hideSetupUI();
        appendMessage('SYS: Systems initialised.', 'sys');
    }
}


// ──────────────────────────────────────────────────────────
//  Helpers
// ──────────────────────────────────────────────────────────

function appendMessage(text, tag) {
    var el = document.createElement('div');
    el.className = 'msg msg-' + tag;
    el.textContent = text;
    transcriptLog.appendChild(el);
    transcriptLog.scrollTop = transcriptLog.scrollHeight;
    msgCount++;
    if (msgCountEl) msgCountEl.textContent = msgCount;
    while (transcriptLog.children.length > 200) {
        transcriptLog.removeChild(transcriptLog.firstChild);
    }
}

function updateMicUI() {
    micBtn.classList.toggle('active', micActive);
    micLabel.textContent = micActive ? 'LISTENING' : 'MIC OFF';
}

function updateStatusText() {
    var el = statusText;
    el.classList.remove('speaking', 'listening');
    var msgSpan = el.querySelector('.status-msg');
    if (speaking) {
        el.classList.add('speaking');
        msgSpan.textContent = 'SPEAKING';
    } else if (micActive) {
        el.classList.add('listening');
        msgSpan.textContent = 'LISTENING';
    } else {
        msgSpan.textContent = 'STANDBY';
    }
}

function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

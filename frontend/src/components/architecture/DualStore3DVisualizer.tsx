import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Play, RotateCcw, ShieldCheck, Zap } from 'lucide-react';

export const DualStore3DVisualizer: React.FC = () => {
  const mountRef = useRef<HTMLDivElement>(null);
  const [pulseActive, setPulseActive] = useState(false);
  const [activeSide, setActiveSide] = useState<'both' | 'falkor' | 'timescale'>('both');

  const triggerPulseRef = useRef<() => void>(() => {});

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 800;
    let height = container.clientHeight || 340;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 4.2, 10.5);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // ==========================================
    // 1. LEFT REACTOR: FALKORDB (GRAPH + VECTOR RAG)
    // ==========================================
    const falkorGroup = new THREE.Group();
    falkorGroup.position.set(-3.2, 0, 0);
    mainGroup.add(falkorGroup);

    // Graph Base Ring
    const falkorRingGeom = new THREE.RingGeometry(1.6, 1.68, 48);
    const falkorRingMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.35,
    });
    const falkorRing = new THREE.Mesh(falkorRingGeom, falkorRingMat);
    falkorRing.rotation.x = Math.PI / 2;
    falkorRing.position.y = -1.2;
    falkorGroup.add(falkorRing);

    // FalkorDB Core Icosahedron (Vector Embeddings Core)
    const falkorCoreGeom = new THREE.IcosahedronGeometry(0.85, 1);
    const falkorCoreMat = new THREE.MeshBasicMaterial({
      color: 0x0284c7,
      wireframe: true,
      transparent: true,
      opacity: 0.8,
    });
    const falkorCore = new THREE.Mesh(falkorCoreGeom, falkorCoreMat);
    falkorGroup.add(falkorCore);

    // Inner Glowing Solid Sphere
    const innerSphereGeom = new THREE.SphereGeometry(0.5, 24, 24);
    const innerSphereMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.65,
    });
    const innerSphere = new THREE.Mesh(innerSphereGeom, innerSphereMat);
    falkorGroup.add(innerSphere);

    // Orbiting Graph Entity Nodes (:Stock, :Commodity, :Macro)
    const graphNodeCount = 6;
    const graphNodes: THREE.Mesh[] = [];
    const nodeGeom = new THREE.SphereGeometry(0.18, 16, 16);
    const nodeColors = [0x38bdf8, 0xf59e0b, 0xa855f7, 0x10b981, 0x38bdf8, 0xf97316];

    for (let i = 0; i < graphNodeCount; i++) {
      const angle = (i / graphNodeCount) * Math.PI * 2;
      const r = 1.6;
      const mesh = new THREE.Mesh(
        nodeGeom,
        new THREE.MeshBasicMaterial({ color: nodeColors[i] })
      );
      mesh.position.set(Math.cos(angle) * r, Math.sin(angle * 2) * 0.4, Math.sin(angle) * r);
      falkorGroup.add(mesh);
      graphNodes.push(mesh);
    }

    // Graph Interconnecting Edges
    const edgeLines: THREE.Line[] = [];
    for (let i = 0; i < graphNodeCount; i++) {
      const nextIdx = (i + 1) % graphNodeCount;
      const pts = [graphNodes[i].position, graphNodes[nextIdx].position];
      const eGeom = new THREE.BufferGeometry().setFromPoints(pts);
      const eMat = new THREE.LineBasicMaterial({
        color: 0x0284c7,
        transparent: true,
        opacity: 0.45,
      });
      const line = new THREE.Line(eGeom, eMat);
      falkorGroup.add(line);
      edgeLines.push(line);

      // Connect to core
      const corePts = [falkorCore.position, graphNodes[i].position];
      const cGeom = new THREE.BufferGeometry().setFromPoints(corePts);
      const cLine = new THREE.Line(
        cGeom,
        new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.25 })
      );
      falkorGroup.add(cLine);
      edgeLines.push(cLine);
    }

    // ==========================================
    // 2. RIGHT REACTOR: TIMESCALEDB (NUMERIC SERIES)
    // ==========================================
    const timescaleGroup = new THREE.Group();
    timescaleGroup.position.set(3.2, 0, 0);
    mainGroup.add(timescaleGroup);

    // Hypertable Columnar Stack Disks
    const diskCount = 5;
    const diskGeom = new THREE.CylinderGeometry(1.2, 1.2, 0.12, 32);
    const diskMat = new THREE.MeshBasicMaterial({
      color: 0x4f46e5,
      transparent: true,
      opacity: 0.55,
      wireframe: false,
    });
    const diskEdgeMat = new THREE.LineBasicMaterial({ color: 0x818cf8, transparent: true, opacity: 0.7 });

    for (let i = 0; i < diskCount; i++) {
      const disk = new THREE.Mesh(diskGeom, diskMat);
      disk.position.y = -1.0 + i * 0.55;
      timescaleGroup.add(disk);

      const edgeGeom = new THREE.EdgesGeometry(diskGeom);
      const edges = new THREE.LineSegments(edgeGeom, diskEdgeMat);
      edges.position.copy(disk.position);
      timescaleGroup.add(edges);
    }

    // Vertical Delivery % / Z-score Frequency Pillars
    const barCount = 8;
    const barGeom = new THREE.BoxGeometry(0.18, 1, 0.18);
    barGeom.translate(0, 0.5, 0);
    const barMeshes: { mesh: THREE.Mesh; baseHeight: number; speed: number; phase: number }[] = [];

    for (let i = 0; i < barCount; i++) {
      const angle = (i / barCount) * Math.PI * 2;
      const r = 0.85;
      const isZscore = i === 2 || i === 6;
      const mat = new THREE.MeshBasicMaterial({
        color: isZscore ? 0xf59e0b : 0x818cf8,
        transparent: true,
        opacity: 0.85,
      });
      const bMesh = new THREE.Mesh(barGeom, mat);
      bMesh.position.set(Math.cos(angle) * r, -1.0, Math.sin(angle) * r);
      timescaleGroup.add(bMesh);
      barMeshes.push({
        mesh: bMesh,
        baseHeight: 0.8 + (i % 3) * 0.4,
        speed: 2.0 + (i % 3) * 0.6,
        phase: i * 0.7,
      });
    }

    // ==========================================
    // 3. CENTER: STRICT INVARIANT CONDUIT BRIDGE
    // ==========================================
    const bridgeGroup = new THREE.Group();
    mainGroup.add(bridgeGroup);

    // Center Firewall Laser Grid (Rule 2: Never store numbers in graph)
    const firewallGeom = new THREE.PlaneGeometry(0.04, 3.2);
    const firewallMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.7,
    });
    const firewallPlane = new THREE.Mesh(firewallGeom, firewallMat);
    firewallPlane.position.set(0, 0, 0);
    bridgeGroup.add(firewallPlane);

    // Dual Arch Beams (Data conduit bridging queries across stores)
    const upperCurve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(-2.2, 0.6, 0),
      new THREE.Vector3(0, 1.6, 0.5),
      new THREE.Vector3(2.2, 0.6, 0)
    );
    const upperGeom = new THREE.BufferGeometry().setFromPoints(upperCurve.getPoints(36));
    const bridgeLineMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.7,
    });
    const upperLine = new THREE.Line(upperGeom, bridgeLineMat);
    bridgeGroup.add(upperLine);

    const lowerCurve = new THREE.QuadraticBezierCurve3(
      new THREE.Vector3(2.2, -0.6, 0),
      new THREE.Vector3(0, -1.6, -0.5),
      new THREE.Vector3(-2.2, -0.6, 0)
    );
    const lowerGeom = new THREE.BufferGeometry().setFromPoints(lowerCurve.getPoints(36));
    const lowerLine = new THREE.Line(
      lowerGeom,
      new THREE.LineBasicMaterial({ color: 0x818cf8, transparent: true, opacity: 0.7 })
    );
    bridgeGroup.add(lowerLine);

    // Traveling Photons along the Conduit (Simulating Dossier Join)
    const photonCount = 10;
    const conduitPhotons: { mesh: THREE.Mesh; isUpper: boolean; progress: number; speed: number }[] = [];
    const pGeom = new THREE.SphereGeometry(0.08, 12, 12);
    const pMatUpper = new THREE.MeshBasicMaterial({ color: 0x38bdf8, blending: THREE.AdditiveBlending });
    const pMatLower = new THREE.MeshBasicMaterial({ color: 0x818cf8, blending: THREE.AdditiveBlending });

    for (let i = 0; i < photonCount; i++) {
      const isUpper = i % 2 === 0;
      const mesh = new THREE.Mesh(pGeom, isUpper ? pMatUpper : pMatLower);
      bridgeGroup.add(mesh);
      conduitPhotons.push({
        mesh,
        isUpper,
        progress: (i / photonCount),
        speed: 0.35 + (i % 2) * 0.15,
      });
    }

    // Trigger Pulse Function
    let pulseProgress = -1;
    triggerPulseRef.current = () => {
      pulseProgress = 0;
      setPulseActive(true);
      setTimeout(() => setPulseActive(false), 2400);
    };

    // Pulse Wave Ring
    const pulseRingGeom = new THREE.RingGeometry(0.1, 0.3, 32);
    const pulseRingMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.9,
    });
    const pulseRing = new THREE.Mesh(pulseRingGeom, pulseRingMat);
    pulseRing.visible = false;
    scene.add(pulseRing);

    // Mouse Interaction
    let targetRotationX = 0;
    let targetRotationY = 0;
    let isDragging = false;
    let prevMouseX = 0;
    let prevMouseY = 0;

    const handleMouseDown = (e: MouseEvent) => {
      isDragging = true;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) {
        const rect = container.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
        targetRotationY = x * 0.35;
        targetRotationX = y * 0.2;
      } else {
        const deltaX = e.clientX - prevMouseX;
        const deltaY = e.clientY - prevMouseY;
        prevMouseX = e.clientX;
        prevMouseY = e.clientY;
        mainGroup.rotation.y += deltaX * 0.008;
        mainGroup.rotation.x += deltaY * 0.008;
      }
    };

    const handleMouseUp = () => {
      isDragging = false;
    };

    container.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);

    const handleResize = () => {
      if (!container) return;
      width = container.clientWidth || 800;
      height = container.clientHeight || 340;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    const resizeObserver = new ResizeObserver(() => handleResize());
    resizeObserver.observe(container);

    let animationId: number;
    const clock = new THREE.Clock();

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      // Smooth camera / group rotation if not dragging
      if (!isDragging) {
        mainGroup.rotation.y += (targetRotationY - mainGroup.rotation.y) * 0.05;
        mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.05;
      }

      // Rotate FalkorDB Core
      falkorCore.rotation.x += 0.008;
      falkorCore.rotation.y += 0.012;
      falkorRing.rotation.z += 0.005;

      // Pulse inner sphere
      const sphereScale = 1 + Math.sin(elapsed * 2.5) * 0.08;
      innerSphere.scale.set(sphereScale, sphereScale, sphereScale);

      // Orbit graph nodes around FalkorDB
      graphNodes.forEach((node, i) => {
        const baseAngle = (i / graphNodeCount) * Math.PI * 2;
        const currentAngle = baseAngle + elapsed * 0.4;
        node.position.set(Math.cos(currentAngle) * 1.6, Math.sin(currentAngle * 2) * 0.35, Math.sin(currentAngle) * 1.6);
      });

      // Rotate TimescaleDB Columns & Oscillate Bars
      timescaleGroup.rotation.y += 0.006;
      barMeshes.forEach((bar) => {
        const h = bar.baseHeight + Math.sin(elapsed * bar.speed + bar.phase) * 0.35;
        bar.mesh.scale.y = Math.max(0.2, h);
      });

      // Animate Conduit Photons (Data joining)
      conduitPhotons.forEach((p) => {
        p.progress += delta * p.speed;
        if (p.progress > 1) p.progress = 0;
        const curve = p.isUpper ? upperCurve : lowerCurve;
        const pt = curve.getPoint(p.progress);
        p.mesh.position.copy(pt);
      });

      // Pulse wave execution
      if (pulseProgress >= 0) {
        pulseProgress += delta * 1.2;
        pulseRing.visible = true;
        const rScale = 0.5 + pulseProgress * 4.5;
        pulseRing.scale.set(rScale, rScale, rScale);
        pulseRingMat.opacity = Math.max(0, 1 - pulseProgress);
        if (pulseProgress > 1) {
          pulseProgress = -1;
          pulseRing.visible = false;
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animationId);
      container.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      resizeObserver.disconnect();
      if (renderer.domElement.parentElement) {
        renderer.domElement.parentElement.removeChild(renderer.domElement);
      }
      renderer.dispose();
      falkorRingGeom.dispose();
      falkorRingMat.dispose();
      falkorCoreGeom.dispose();
      falkorCoreMat.dispose();
      innerSphereGeom.dispose();
      innerSphereMat.dispose();
      nodeGeom.dispose();
      diskGeom.dispose();
      diskMat.dispose();
      diskEdgeMat.dispose();
      barGeom.dispose();
      firewallGeom.dispose();
      firewallMat.dispose();
      upperGeom.dispose();
      lowerGeom.dispose();
      bridgeLineMat.dispose();
      pGeom.dispose();
      pMatUpper.dispose();
      pMatLower.dispose();
      pulseRingGeom.dispose();
      pulseRingMat.dispose();
    };
  }, []);

  return (
    <div className="relative w-full rounded-2xl overflow-hidden bg-ink-0/95 border border-white/10 shadow-2xl mb-8">
      {/* 3D WebGL Canvas Viewport */}
      <div className="relative w-full h-80 sm:h-96">
        <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />

        {/* Top Floating HUD Bar */}
        <div className="absolute top-4 left-4 right-4 flex flex-wrap items-center justify-between gap-3 pointer-events-none">
          <div className="flex items-center gap-2 bg-black/70 backdrop-blur-md px-3 py-1.5 rounded-xl border border-white/10 pointer-events-auto">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            <span className="text-xs font-mono font-bold text-white">DUAL-STORE CONDUIT</span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              Rule 2 Enforced
            </span>
          </div>

          <div className="flex items-center gap-2 pointer-events-auto">
            <button
              onClick={() => triggerPulseRef.current()}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono font-semibold flex items-center gap-1.5 transition shadow-lg ${
                pulseActive
                  ? 'bg-emerald-500 text-black shadow-emerald-500/50'
                  : 'bg-white/10 text-white hover:bg-white/20 border border-white/15'
              }`}
            >
              <Zap className={`w-3.5 h-3.5 ${pulseActive ? 'animate-bounce text-black' : 'text-emerald-400'}`} />
              <span>{pulseActive ? 'Executing Conduit Join...' : 'Simulate Dossier Join'}</span>
            </button>
          </div>
        </div>

        {/* Floating Sector Badges (Left & Right) */}
        <div className="absolute bottom-4 left-4 pointer-events-none">
          <div className="bg-black/80 backdrop-blur-md p-2.5 rounded-xl border border-sky-500/30 text-left max-w-xs">
            <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-sky-400">
              <span className="w-2 h-2 rounded-full bg-sky-400" />
              <span>FALKORDB GRAPH REACTOR</span>
            </div>
            <div className="text-[11px] font-mono text-slate-400 mt-0.5">
              Nodes, Edges, vecf32 embeddings, zero numeric floats
            </div>
          </div>
        </div>

        <div className="absolute bottom-4 right-4 pointer-events-none">
          <div className="bg-black/80 backdrop-blur-md p-2.5 rounded-xl border border-indigo-500/30 text-right max-w-xs">
            <div className="flex items-center justify-end gap-1.5 text-xs font-mono font-bold text-indigo-400">
              <span>TIMESCALEDB NUMERIC SILO</span>
              <span className="w-2 h-2 rounded-full bg-indigo-400" />
            </div>
            <div className="text-[11px] font-mono text-slate-400 mt-0.5">
              Bhavcopy CSVs, delivery % z-scores, 2 checkpoints/day
            </div>
          </div>
        </div>

        {/* Center Invariant Plaque */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none hidden sm:block">
          <div className="px-3 py-1 rounded-full bg-black/85 backdrop-blur-md border border-emerald-500/40 text-[10px] font-mono text-emerald-300 shadow-xl flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>NO FLOATS IN GRAPH CORE</span>
          </div>
        </div>
      </div>
    </div>
  );
};


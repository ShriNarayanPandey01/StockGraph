import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

export const PillarBhavcopyVisual: React.FC = () => {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 300;
    let height = container.clientHeight || 180;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 4.5, 7.5);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // Group for mouse tilt
    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // 1. Grid plane (Hypertable time baseline)
    const gridHelper = new THREE.GridHelper(6, 12, 0x38bdf8, 0x1e293b);
    gridHelper.position.y = -0.5;
    mainGroup.add(gridHelper);

    // 2. Dual-Session 3D Bars (OPEN vs CLOSE checkpoints)
    const barCount = 10;
    const barsGroup = new THREE.Group();
    mainGroup.add(barsGroup);

    const barGeom = new THREE.BoxGeometry(0.24, 1, 0.24);
    // Shift geometry anchor to base
    barGeom.translate(0, 0.5, 0);

    const cyanMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.85,
      wireframe: false,
    });

    const indigoMat = new THREE.MeshBasicMaterial({
      color: 0x6366f1,
      transparent: true,
      opacity: 0.75,
      wireframe: false,
    });

    const anomalyMat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      transparent: true,
      opacity: 0.95,
    });

    const barMeshes: { mesh: THREE.Mesh; baseHeight: number; speed: number; phase: number }[] = [];

    for (let i = 0; i < barCount; i++) {
      const x = (i - barCount / 2 + 0.5) * 0.52;
      
      // OPEN bar (morning checkpoint)
      const openMesh = new THREE.Mesh(barGeom, indigoMat);
      openMesh.position.set(x, -0.5, -0.4);
      barsGroup.add(openMesh);
      barMeshes.push({
        mesh: openMesh,
        baseHeight: 0.6 + Math.sin(i * 0.7) * 0.4,
        speed: 1.8 + (i % 3) * 0.4,
        phase: i * 0.5,
      });

      // CLOSE bar (evening Bhavcopy checkpoint + delivery % volume)
      const isAnomaly = i === 6 || i === 3; // delivery zscore >= 1.8
      const closeMesh = new THREE.Mesh(barGeom, isAnomaly ? anomalyMat : cyanMat);
      closeMesh.position.set(x, -0.5, 0.4);
      barsGroup.add(closeMesh);
      barMeshes.push({
        mesh: closeMesh,
        baseHeight: isAnomaly ? 2.2 : 1.1 + Math.cos(i * 0.8) * 0.6,
        speed: 2.2 + (i % 2) * 0.5,
        phase: i * 0.8 + 1.2,
      });
    }

    // 3. Horizontal Z-score threshold plane (+1.8 sigma threshold indicator)
    const thresholdGeom = new THREE.BufferGeometry();
    const thresholdPoints = [
      new THREE.Vector3(-2.8, 1.2, -1.2),
      new THREE.Vector3(2.8, 1.2, -1.2),
      new THREE.Vector3(2.8, 1.2, 1.2),
      new THREE.Vector3(-2.8, 1.2, 1.2),
      new THREE.Vector3(-2.8, 1.2, -1.2),
    ];
    thresholdGeom.setFromPoints(thresholdPoints);
    const thresholdLine = new THREE.Line(
      thresholdGeom,
      new THREE.LineDashedMaterial({
        color: 0xf59e0b,
        dashSize: 0.2,
        gapSize: 0.1,
        transparent: true,
        opacity: 0.65,
      })
    );
    thresholdLine.computeLineDistances();
    mainGroup.add(thresholdLine);

    // 4. Floating Bhavcopy CSV particle stream
    const particleCount = 40;
    const particleGeo = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      particlePositions[i * 3] = (Math.random() - 0.5) * 5;
      particlePositions[i * 3 + 1] = Math.random() * 2.5 - 0.5;
      particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 3;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    const particleMat = new THREE.PointsMaterial({
      color: 0x38bdf8,
      size: 0.08,
      transparent: true,
      opacity: 0.7,
      blending: THREE.AdditiveBlending,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    mainGroup.add(particles);

    // Interactive mouse parallax
    let targetRotationX = 0;
    let targetRotationY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetRotationY = x * 0.45;
      targetRotationX = y * 0.25;
    };

    container.addEventListener('mousemove', handleMouseMove);

    // Resize observer
    const handleResize = () => {
      if (!container) return;
      width = container.clientWidth || 300;
      height = container.clientHeight || 180;
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
      const elapsed = clock.getElapsedTime();

      // Smooth mouse follow
      mainGroup.rotation.y += (targetRotationY - mainGroup.rotation.y) * 0.06;
      mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.06;

      // Animate bar oscillations (simulating dual-session time series ingestion)
      barMeshes.forEach((bar) => {
        const scaleY = bar.baseHeight + Math.sin(elapsed * bar.speed + bar.phase) * 0.25;
        bar.mesh.scale.y = Math.max(0.15, scaleY);
      });

      // Animate floating particles
      const positions = particleGeo.attributes.position.array as Float32Array;
      for (let i = 0; i < particleCount; i++) {
        positions[i * 3 + 1] += 0.008;
        if (positions[i * 3 + 1] > 2.2) {
          positions[i * 3 + 1] = -0.5;
        }
      }
      particleGeo.attributes.position.needsUpdate = true;

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animationId);
      container.removeEventListener('mousemove', handleMouseMove);
      resizeObserver.disconnect();
      if (renderer.domElement.parentElement) {
        renderer.domElement.parentElement.removeChild(renderer.domElement);
      }
      renderer.dispose();
      barGeom.dispose();
      cyanMat.dispose();
      indigoMat.dispose();
      anomalyMat.dispose();
      thresholdGeom.dispose();
      particleGeo.dispose();
      particleMat.dispose();
    };
  }, []);

  return (
    <div className="relative w-full h-44 rounded-xl overflow-hidden bg-gradient-to-b from-ink-0/60 to-ink-1/90 border border-sky-500/15 group-hover:border-sky-500/35 transition-all">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-0.5 rounded bg-black/60 border border-sky-500/30 text-[10px] font-mono text-sky-300 pointer-events-none">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping" />
        <span>NSE Bhavcopy: 2 Checkpoints (OPEN/CLOSE)</span>
      </div>
      <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/60 border border-amber-500/30 text-[9px] font-mono text-amber-300 pointer-events-none">
        Anomaly Threshold: abs(z) ≥ 1.8σ
      </div>
    </div>
  );
};


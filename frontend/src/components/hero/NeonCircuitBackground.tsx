import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface Point {
  x: number;
  y: number;
}

interface CircuitPath {
  points: Point[];
  totalLength: number;
  segmentLengths: number[];
  color: string;
  glowColor: string;
}

interface LedPulse {
  pathIndex: number;
  progress: number;
  speed: number;
  length: number;
  color: string;
  glowColor: string;
  size: number;
}

export const NeonCircuitBackground: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const threeMountRef = useRef<HTMLDivElement>(null);

  // 1. Three.js Subtle Ambient Particle Layer
  useEffect(() => {
    const threeContainer = threeMountRef.current;
    if (!threeContainer) return;

    const width = threeContainer.clientWidth;
    const height = threeContainer.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 1000);
    camera.position.z = 25;

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    threeContainer.appendChild(renderer.domElement);

    // Minimal Drifting Cyber Particles
    const particleCount = 45;
    const particleGeo = new THREE.BufferGeometry();
    const particlePositions = new Float32Array(particleCount * 3);
    const particleColors = new Float32Array(particleCount * 3);

    const cyan = new THREE.Color(0x38bdf8);
    const purple = new THREE.Color(0x818cf8);

    for (let i = 0; i < particleCount; i++) {
      particlePositions[i * 3] = (Math.random() - 0.5) * 45;
      particlePositions[i * 3 + 1] = (Math.random() - 0.5) * 30;
      particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 15;

      const mixed = Math.random() > 0.5 ? cyan : purple;
      particleColors[i * 3] = mixed.r;
      particleColors[i * 3 + 1] = mixed.g;
      particleColors[i * 3 + 2] = mixed.b;
    }

    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 0.18,
      vertexColors: true,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending,
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    let mouseX = 0;
    let mouseY = 0;
    let targetX = 0;
    let targetY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = threeContainer.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetX = x * 1.5;
      targetY = y * 1.2;
    };

    window.addEventListener('mousemove', handleMouseMove);

    let animId: number;
    let clock = new THREE.Clock();

    const animateThree = () => {
      const elapsed = clock.getElapsedTime();

      // Smooth subtle camera drift
      mouseX += (targetX - mouseX) * 0.03;
      mouseY += (targetY - mouseY) * 0.03;
      camera.position.x = mouseX;
      camera.position.y = mouseY;
      camera.lookAt(0, 0, 0);

      particles.rotation.y = elapsed * 0.012;

      renderer.render(scene, camera);
      animId = requestAnimationFrame(animateThree);
    };

    animateThree();

    const handleResize = () => {
      if (!threeContainer) return;
      const nw = threeContainer.clientWidth;
      const nh = threeContainer.clientHeight;
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animId);
      if (renderer.domElement && threeContainer.contains(renderer.domElement)) {
        threeContainer.removeChild(renderer.domElement);
      }
      renderer.dispose();
    };
  }, []);

  // 2. Hardware-Accelerated Minimal Neon LED Circuit Lines (Reduced to 2 subtle paths)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    let width = (canvas.width = canvas.parentElement?.clientWidth || window.innerWidth);
    let height = (canvas.height = canvas.parentElement?.clientHeight || window.innerHeight);

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    // Mouse parallax offset
    let pMouseX = 0;
    let pMouseY = 0;
    let tMouseX = 0;
    let tMouseY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      tMouseX = ((e.clientX - rect.left) / width - 0.5) * 12;
      tMouseY = ((e.clientY - rect.top) / height - 0.5) * 10;
    };
    window.addEventListener('mousemove', handleMouseMove);

    // REDUCED: Exactly 2 clean, elegant, minimal accent lines
    const rawPaths: { normalized: Point[]; color: string; glow: string }[] = [
      // Line 1: Elegant upper-left to mid-right circuit trace
      {
        normalized: [
          { x: -0.05, y: 0.22 },
          { x: 0.25, y: 0.22 },
          { x: 0.32, y: 0.29 },
          { x: 0.68, y: 0.29 },
          { x: 0.74, y: 0.23 },
          { x: 1.05, y: 0.23 },
        ],
        color: '#0284c7',
        glow: '#38bdf8',
      },
      // Line 2: Subtle lower perimeter circuit trace
      {
        normalized: [
          { x: -0.05, y: 0.78 },
          { x: 0.2, y: 0.78 },
          { x: 0.26, y: 0.72 },
          { x: 0.72, y: 0.72 },
          { x: 0.78, y: 0.78 },
          { x: 1.05, y: 0.78 },
        ],
        color: '#6366f1',
        glow: '#a855f7',
      },
    ];

    let circuitPaths: CircuitPath[] = [];

    const buildPaths = () => {
      circuitPaths = rawPaths.map((rp) => {
        const points = rp.normalized.map((p) => ({
          x: p.x * width,
          y: p.y * height,
        }));

        let totalLength = 0;
        const segmentLengths: number[] = [];

        for (let i = 0; i < points.length - 1; i++) {
          const dx = points[i + 1].x - points[i].x;
          const dy = points[i + 1].y - points[i].y;
          const dist = Math.hypot(dx, dy);
          segmentLengths.push(dist);
          totalLength += dist;
        }

        return {
          points,
          totalLength,
          segmentLengths,
          color: rp.color,
          glowColor: rp.glow,
        };
      });
    };

    buildPaths();

    // REDUCED: Exactly 2 calm, smooth LED pulses (one per path)
    const pulses: LedPulse[] = [
      { pathIndex: 0, progress: 0.2, speed: 0.0012, length: 110, color: '#ffffff', glowColor: '#38bdf8', size: 2.8 },
      { pathIndex: 1, progress: 0.6, speed: 0.001, length: 110, color: '#ffffff', glowColor: '#c084fc', size: 2.8 },
    ];

    const getPointAtDistance = (path: CircuitPath, distance: number): Point => {
      let d = ((distance % path.totalLength) + path.totalLength) % path.totalLength;
      for (let i = 0; i < path.segmentLengths.length; i++) {
        const segLen = path.segmentLengths[i];
        if (d <= segLen) {
          const ratio = segLen === 0 ? 0 : d / segLen;
          const p1 = path.points[i];
          const p2 = path.points[i + 1];
          return {
            x: p1.x + (p2.x - p1.x) * ratio,
            y: p1.y + (p2.y - p1.y) * ratio,
          };
        }
        d -= segLen;
      }
      return path.points[path.points.length - 1];
    };

    let animationId: number;

    const render = () => {
      pMouseX += (tMouseX - pMouseX) * 0.05;
      pMouseY += (tMouseY - pMouseY) * 0.05;

      ctx.clearRect(0, 0, width, height);

      ctx.save();
      ctx.translate(pMouseX, pMouseY);

      // Base Lines (Subtle & Clean)
      ctx.lineWidth = 1.2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';

      circuitPaths.forEach((path) => {
        if (path.points.length < 2) return;

        // Subtle faint track
        ctx.strokeStyle = path.color;
        ctx.globalAlpha = 0.22;
        ctx.beginPath();
        ctx.moveTo(path.points[0].x, path.points[0].y);
        for (let i = 1; i < path.points.length; i++) {
          ctx.lineTo(path.points[i].x, path.points[i].y);
        }
        ctx.stroke();

        // Subtle junction pin dots
        ctx.globalAlpha = 0.35;
        path.points.forEach((pt) => {
          ctx.fillStyle = path.glowColor;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 1.8, 0, Math.PI * 2);
          ctx.fill();
        });
      });

      // Animate the 2 Smooth Neon LED Pulses
      pulses.forEach((pulse) => {
        const path = circuitPaths[pulse.pathIndex];
        if (!path || path.totalLength === 0) return;

        pulse.progress = (pulse.progress + pulse.speed) % 1.0;
        const headDist = pulse.progress * path.totalLength;

        // Glowing light tail
        const samples = 12;
        const stepDist = pulse.length / samples;

        for (let s = samples; s >= 1; s--) {
          const d1 = headDist - s * stepDist;
          const d2 = headDist - (s - 1) * stepDist;

          const pt1 = getPointAtDistance(path, d1);
          const pt2 = getPointAtDistance(path, d2);

          const tailAlpha = Math.pow((samples - s) / samples, 1.8) * 0.65;

          ctx.strokeStyle = pulse.glowColor;
          ctx.lineWidth = 1.5;
          ctx.globalAlpha = tailAlpha;
          ctx.beginPath();
          ctx.moveTo(pt1.x, pt1.y);
          ctx.lineTo(pt2.x, pt2.y);
          ctx.stroke();
        }

        // Intense Neon LED Head
        const head = getPointAtDistance(path, headDist);

        // Soft outer glow
        const radGrad = ctx.createRadialGradient(head.x, head.y, 0, head.x, head.y, 14);
        radGrad.addColorStop(0, pulse.glowColor);
        radGrad.addColorStop(1, 'rgba(0,0,0,0)');

        ctx.fillStyle = radGrad;
        ctx.globalAlpha = 0.45;
        ctx.beginPath();
        ctx.arc(head.x, head.y, 14, 0, Math.PI * 2);
        ctx.fill();

        // Crisp glowing head
        ctx.fillStyle = pulse.glowColor;
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.arc(head.x, head.y, pulse.size, 0, Math.PI * 2);
        ctx.fill();

        // White core
        ctx.fillStyle = '#ffffff';
        ctx.globalAlpha = 1.0;
        ctx.beginPath();
        ctx.arc(head.x, head.y, pulse.size * 0.5, 0, Math.PI * 2);
        ctx.fill();
      });

      ctx.restore();
      animationId = requestAnimationFrame(render);
    };

    render();

    const handleWindowResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.parentElement.clientWidth;
      height = canvas.parentElement.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.scale(dpr, dpr);
      buildPaths();
    };

    window.addEventListener('resize', handleWindowResize);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('resize', handleWindowResize);
      cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <div ref={containerRef} className="absolute inset-0 overflow-hidden pointer-events-none select-none z-0">
      {/* 1. Deep Space Atmosphere Gradient */}
      <div className="absolute inset-0 bg-[#060814]" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(15,23,42,0.85)_0%,rgba(6,8,20,0.98)_70%)]" />

      {/* 2. Three.js Subtle Ambient Particle Layer */}
      <div ref={threeMountRef} className="absolute inset-0 opacity-40" />

      {/* 3. Minimal Neon LED Circuit Lines */}
      <canvas ref={canvasRef} className="absolute inset-0 block" />

      {/* 4. Ambient Glow */}
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[350px] bg-sky-500/10 rounded-full blur-[140px] pointer-events-none" />
    </div>
  );
};

import React, { useEffect, useRef } from 'react';

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  size: number;
  color: string;
  isStar: boolean;
}

export const WavyRocketCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

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

    // Particle pool for thruster wake
    const particles: Particle[] = [];
    const particleColors = ['#38bdf8', '#facc15', '#f97316', '#c084fc', '#ffffff', '#ec4899'];

    // Flight parameters
    // Trajectory runs from bottom-left to top-right in a wavy pattern
    let progress = 0; // 0.0 to 1.0 (with a brief pause offscreen)
    const flightSpeed = 0.0016; // Takes ~10 seconds per crossing
    const waveFrequency = 2.5; // ~2.5 full wave crests across the screen
    const waveAmplitude = 75; // Amplitude of sine wave oscillation (pixels)

    // Calculate position along wavy path
    const getWavyPosition = (p: number) => {
      // Offscreen margins so the rocket enters and leaves completely
      const startX = -120;
      const startY = height + 100;
      const endX = width + 140;
      const endY = -120;

      // Base linear diagonal vector
      const dx = endX - startX;
      const dy = endY - startY;
      const diagLen = Math.hypot(dx, dy);

      // Unit normal vector perpendicular to diagonal (pointing upwards-left)
      const nx = -dy / diagLen;
      const ny = dx / diagLen;

      // Diagonal interpolation
      const bx = startX + p * dx;
      const by = startY + p * dy;

      // Sine wave displacement perpendicular to the flight path
      // Smooth fade at the very edges so entry and exit are smooth
      const edgeWeight = Math.sin(Math.min(Math.max(p, 0), 1) * Math.PI);
      const wave = Math.sin(p * Math.PI * 2 * waveFrequency) * waveAmplitude * (0.6 + 0.4 * edgeWeight);

      return {
        x: bx + nx * wave,
        y: by + ny * wave,
      };
    };

    let animationFrameId: number;
    let clockTime = 0;

    const render = () => {
      clockTime += 0.016;
      ctx.clearRect(0, 0, width, height);

      // Update progress
      progress += flightSpeed;
      if (progress > 1.18) {
        // Reset back to bottom-left after clearing off-screen
        progress = -0.05;
      }

      // Compute current position and heading angle
      const currentPos = getWavyPosition(progress);
      // Small delta to determine velocity vector / rotation angle
      const forwardPos = getWavyPosition(progress + 0.004);
      const headingAngle = Math.atan2(forwardPos.y - currentPos.y, forwardPos.x - currentPos.x);

      // Rocket is active and on/near screen
      const isVisible = progress >= -0.05 && progress <= 1.1;

      // 1. Emit exhaust stardust particles from rocket nozzle
      if (isVisible) {
        // Rocket nozzle position in world coordinates (behind rocket)
        const nozzleDist = -48;
        const nozzleX = currentPos.x + Math.cos(headingAngle) * nozzleDist;
        const nozzleY = currentPos.y + Math.sin(headingAngle) * nozzleDist;

        // Spawn 2-3 particles per frame
        const spawnCount = Math.random() > 0.4 ? 2 : 1;
        for (let i = 0; i < spawnCount; i++) {
          const spread = (Math.random() - 0.5) * 0.5;
          const speed = 1.8 + Math.random() * 2.2;
          const pAngle = headingAngle + Math.PI + spread;

          particles.push({
            x: nozzleX + (Math.random() - 0.5) * 6,
            y: nozzleY + (Math.random() - 0.5) * 6,
            vx: Math.cos(pAngle) * speed + (Math.random() - 0.5) * 0.4,
            vy: Math.sin(pAngle) * speed + (Math.random() - 0.5) * 0.4,
            life: 1.0,
            maxLife: 40 + Math.random() * 35,
            size: 2.0 + Math.random() * 4.0,
            color: particleColors[Math.floor(Math.random() * particleColors.length)],
            isStar: Math.random() > 0.65,
          });
        }
      }

      // 2. Render & Update Particle Trail
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        p.vx *= 0.98;
        p.vy *= 0.98;
        p.life -= 1 / p.maxLife;

        if (p.life <= 0) {
          particles.splice(i, 1);
          continue;
        }

        ctx.save();
        ctx.globalAlpha = Math.max(0, p.life * 0.75);

        if (p.isStar) {
          // Draw sparkling 4-point star
          ctx.fillStyle = p.color;
          ctx.translate(p.x, p.y);
          const r = p.size * p.life;
          ctx.beginPath();
          ctx.moveTo(0, -r * 1.5);
          ctx.quadraticCurveTo(0, 0, r * 1.5, 0);
          ctx.quadraticCurveTo(0, 0, 0, r * 1.5);
          ctx.quadraticCurveTo(0, 0, -r * 1.5, 0);
          ctx.quadraticCurveTo(0, 0, 0, -r * 1.5);
          ctx.fill();
        } else {
          // Draw soft glowing stardust circle
          ctx.fillStyle = p.color;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size * (0.4 + 0.6 * p.life), 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      // 3. Render the Character Sitting on the Rocket
      if (isVisible) {
        ctx.save();
        ctx.translate(currentPos.x, currentPos.y);
        ctx.rotate(headingAngle);

        // Rocket scale (crisp and proportioned)
        const scale = 0.95;
        ctx.scale(scale, scale);

        // A. Thruster Flame (Animated dynamic flicker)
        const flameFlicker = Math.sin(clockTime * 35) * 6 + (Math.random() - 0.5) * 8;
        const flameLength = 55 + flameFlicker;

        // Outer Plasma Flame (Cyan & Violet)
        const outerGrad = ctx.createLinearGradient(-44, 0, -44 - flameLength * 1.2, 0);
        outerGrad.addColorStop(0, '#38bdf8');
        outerGrad.addColorStop(0.5, '#a855f7');
        outerGrad.addColorStop(1, 'rgba(168, 85, 247, 0)');
        ctx.fillStyle = outerGrad;
        ctx.beginPath();
        ctx.moveTo(-44, -12);
        ctx.quadraticCurveTo(-44 - flameLength * 0.6, -14, -44 - flameLength * 1.2, 0);
        ctx.quadraticCurveTo(-44 - flameLength * 0.6, 14, -44, 12);
        ctx.closePath();
        ctx.fill();

        // Mid Fire Flame (Electric Orange)
        const midGrad = ctx.createLinearGradient(-44, 0, -44 - flameLength * 0.8, 0);
        midGrad.addColorStop(0, '#f97316');
        midGrad.addColorStop(0.7, '#ef4444');
        midGrad.addColorStop(1, 'rgba(239, 68, 68, 0)');
        ctx.fillStyle = midGrad;
        ctx.beginPath();
        ctx.moveTo(-44, -8);
        ctx.quadraticCurveTo(-44 - flameLength * 0.4, -9, -44 - flameLength * 0.8, 0);
        ctx.quadraticCurveTo(-44 - flameLength * 0.4, 9, -44, 8);
        ctx.closePath();
        ctx.fill();

        // Inner Intense Core (White-Yellow)
        const coreGrad = ctx.createLinearGradient(-44, 0, -44 - flameLength * 0.45, 0);
        coreGrad.addColorStop(0, '#ffffff');
        coreGrad.addColorStop(0.8, '#fef08a');
        coreGrad.addColorStop(1, 'rgba(254, 240, 138, 0)');
        ctx.fillStyle = coreGrad;
        ctx.beginPath();
        ctx.moveTo(-44, -4.5);
        ctx.lineTo(-44 - flameLength * 0.45, 0);
        ctx.lineTo(-44, 4.5);
        ctx.closePath();
        ctx.fill();

        // B. Rocket Rear Nozzle
        ctx.fillStyle = '#1e293b';
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(-34, -10);
        ctx.lineTo(-44, -13);
        ctx.lineTo(-44, 13);
        ctx.lineTo(-34, 10);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // C. Rocket Stabilizer Fins
        // Top Fin
        ctx.fillStyle = '#0284c7';
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(-16, -14);
        ctx.lineTo(-36, -30);
        ctx.lineTo(-40, -14);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Bottom Fin
        ctx.beginPath();
        ctx.moveTo(-16, 14);
        ctx.lineTo(-36, 30);
        ctx.lineTo(-40, 14);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // D. Rocket Main Fuselage (Aerodynamic Body)
        const bodyGrad = ctx.createLinearGradient(0, -16, 0, 16);
        bodyGrad.addColorStop(0, '#ffffff');
        bodyGrad.addColorStop(0.4, '#f1f5f9');
        bodyGrad.addColorStop(0.8, '#cbd5e1');
        bodyGrad.addColorStop(1, '#94a3b8');

        ctx.fillStyle = bodyGrad;
        ctx.strokeStyle = '#64748b';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        // Nose tip
        ctx.moveTo(56, 0);
        // Top curve
        ctx.quadraticCurveTo(28, -15, -34, -14);
        // Back
        ctx.lineTo(-34, 14);
        // Bottom curve
        ctx.quadraticCurveTo(28, 15, 56, 0);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Cyan / Sky-Blue Aerodynamic Nose Cone
        const noseGrad = ctx.createLinearGradient(28, 0, 56, 0);
        noseGrad.addColorStop(0, '#0284c7');
        noseGrad.addColorStop(1, '#38bdf8');
        ctx.fillStyle = noseGrad;
        ctx.beginPath();
        ctx.moveTo(56, 0);
        ctx.quadraticCurveTo(42, -10, 26, -13.5);
        ctx.quadraticCurveTo(28, 0, 26, 13.5);
        ctx.quadraticCurveTo(42, 10, 56, 0);
        ctx.closePath();
        ctx.fill();

        // High-Tech Racing Stripe
        ctx.fillStyle = '#0ea5e9';
        ctx.beginPath();
        ctx.moveTo(14, -14);
        ctx.lineTo(20, -13.5);
        ctx.lineTo(16, 13.5);
        ctx.lineTo(10, 14);
        ctx.closePath();
        ctx.fill();

        ctx.fillStyle = '#a855f7';
        ctx.beginPath();
        ctx.moveTo(2, -14.2);
        ctx.lineTo(6, -14);
        ctx.lineTo(2, 14);
        ctx.lineTo(-2, 14.2);
        ctx.closePath();
        ctx.fill();

        // Side Fin (Facing viewer)
        ctx.fillStyle = '#38bdf8';
        ctx.beginPath();
        ctx.moveTo(-10, 2);
        ctx.lineTo(-32, 11);
        ctx.lineTo(-26, 3);
        ctx.closePath();
        ctx.fill();

        // E. CHARACTER SITTING ON TOP OF THE ROCKET (Riding Posture)
        // 1. Character Legs (Straddling rocket body)
        // Back leg (thigh hugging rocket side)
        ctx.fillStyle = '#334155';
        ctx.beginPath();
        ctx.moveTo(-2, -12);
        ctx.quadraticCurveTo(8, -2, 4, 6);
        ctx.lineTo(-2, 4);
        ctx.quadraticCurveTo(2, -6, -8, -12);
        ctx.closePath();
        ctx.fill();

        // Boots (Cyan space boots)
        ctx.fillStyle = '#38bdf8';
        ctx.beginPath();
        ctx.ellipse(3, 7, 4.5, 3, Math.PI / 4, 0, Math.PI * 2);
        ctx.fill();

        // 2. Character Torso & Space Suit
        const suitGrad = ctx.createLinearGradient(-10, -32, 8, -14);
        suitGrad.addColorStop(0, '#f8fafc');
        suitGrad.addColorStop(1, '#cbd5e1');
        ctx.fillStyle = suitGrad;
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(-8, -13);
        ctx.lineTo(-5, -28);
        ctx.lineTo(6, -26);
        ctx.lineTo(4, -13);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Life-Support Space Backpack
        ctx.fillStyle = '#0f172a';
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.roundRect(-14, -28, 7, 14, 2);
        ctx.fill();
        ctx.stroke();

        // Backpack indicator light
        ctx.fillStyle = Math.sin(clockTime * 10) > 0 ? '#34d399' : '#0284c7';
        ctx.beginPath();
        ctx.arc(-10.5, -24, 1.2, 0, Math.PI * 2);
        ctx.fill();

        // 3. Hands & Arms
        // Right Arm (Holding onto rocket handlebars)
        ctx.fillStyle = '#e2e8f0';
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(3, -24);
        ctx.quadraticCurveTo(10, -20, 14, -15);
        ctx.lineTo(12, -13);
        ctx.quadraticCurveTo(8, -17, 1, -22);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Cyan Glove holding rocket handlebar
        ctx.fillStyle = '#38bdf8';
        ctx.beginPath();
        ctx.arc(14, -15, 3, 0, Math.PI * 2);
        ctx.fill();

        // Rocket steering grip / windshield peg
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(14, -13);
        ctx.lineTo(14, -17);
        ctx.stroke();

        // Left Arm (Raised waving forward happily!)
        ctx.fillStyle = '#f1f5f9';
        ctx.beginPath();
        ctx.moveTo(-2, -26);
        ctx.quadraticCurveTo(6, -34, 12, -38);
        ctx.lineTo(14, -36);
        ctx.quadraticCurveTo(8, -32, 0, -24);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Glove waving
        ctx.fillStyle = '#a855f7';
        ctx.beginPath();
        ctx.arc(13, -37, 3.2, 0, Math.PI * 2);
        ctx.fill();

        // 4. Fluttering Space Scarf (Waving dynamically in the cosmic wind)
        const scarfWave1 = Math.sin(clockTime * 14) * 4;
        const scarfWave2 = Math.cos(clockTime * 14) * 3;
        ctx.fillStyle = '#f43f5e';
        ctx.beginPath();
        ctx.moveTo(-2, -27);
        ctx.quadraticCurveTo(-14, -28 + scarfWave1, -26, -26 + scarfWave2);
        ctx.lineTo(-24, -22 + scarfWave2);
        ctx.quadraticCurveTo(-12, -24 + scarfWave1, 0, -25);
        ctx.closePath();
        ctx.fill();

        // 5. Astronaut Helmet (Bubble helmet with reflecting visor)
        const helmetX = 3;
        const helmetY = -35;
        const helmetR = 10;

        // Helmet base
        ctx.fillStyle = '#f8fafc';
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(helmetX, helmetY, helmetR, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Helmet reflective visor (Dark cyber glass with cyan/purple gradient)
        const visorGrad = ctx.createLinearGradient(helmetX - 3, helmetY - 7, helmetX + 8, helmetY + 6);
        visorGrad.addColorStop(0, '#0f172a');
        visorGrad.addColorStop(0.4, '#1e1b4b');
        visorGrad.addColorStop(0.8, '#06b6d4');
        visorGrad.addColorStop(1, '#a855f7');

        ctx.fillStyle = visorGrad;
        ctx.beginPath();
        // Visor facing forward (right)
        ctx.arc(helmetX + 2, helmetY, 7.5, -Math.PI / 2.2, Math.PI / 2.2, false);
        ctx.closePath();
        ctx.fill();

        // Visor specular shine
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.75)';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(helmetX + 3.5, helmetY - 1.5, 4.5, -Math.PI / 2.5, -Math.PI / 6);
        ctx.stroke();

        // Helmet Cute Antenna
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(helmetX, helmetY - helmetR);
        ctx.lineTo(helmetX - 2, helmetY - helmetR - 6);
        ctx.stroke();

        // Glowing antenna beacon tip
        ctx.fillStyle = '#38bdf8';
        ctx.shadowColor = '#38bdf8';
        ctx.shadowBlur = 6;
        ctx.beginPath();
        ctx.arc(helmetX - 2, helmetY - helmetR - 6, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0; // reset shadow

        ctx.restore();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.parentElement.clientWidth;
      height = canvas.parentElement.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.scale(dpr, dpr);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div className="absolute inset-0 pointer-events-none select-none overflow-hidden z-10">
      <canvas ref={canvasRef} className="absolute inset-0 block w-full h-full" />
    </div>
  );
};


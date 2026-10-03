/**
 * Epoch Hero Canvas Frame Scrubber
 * Drives high-fidelity scrubbing of 150 WebP frames with GSAP ScrollTrigger
 */

(function () {
  'use strict';

  // Check reduced motion preference
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canvas = document.getElementById('hero-canvas');
  const fallbackVideo = document.querySelector('.hero-video-fallback');
  const scrollContainer = document.querySelector('.hero-scroll-container');
  const beats = document.querySelectorAll('.hero-beat');

  if (prefersReducedMotion || !canvas) {
    if (fallbackVideo) fallbackVideo.style.display = 'block';
    if (canvas) canvas.style.display = 'none';
    beats.forEach((b) => {
      b.style.opacity = '1';
      b.style.transform = 'none';
      b.classList.add('active');
    });
    return;
  }

  const ctx = canvas.getContext('2d', { alpha: false });
  let currentSet = 'd';
  let totalFrames = 150;
  const frameImages = new Array(totalFrames);
  let currentRenderedIndex = -1;

  // Setup Canvas Dimensions (retina support)
  function resizeCanvas() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    if (currentRenderedIndex >= 0) {
      drawFrame(currentRenderedIndex);
    }
  }

  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  // Draw Frame with Object-Fit: Cover
  function drawFrame(idx) {
    let img = frameImages[idx];
    if (!img || !img.complete || img.naturalWidth === 0) {
      // Find nearest loaded frame as fallback
      for (let offset = 1; offset < 20; offset++) {
        if (frameImages[idx - offset]?.complete && frameImages[idx - offset].naturalWidth > 0) {
          img = frameImages[idx - offset];
          break;
        }
        if (frameImages[idx + offset]?.complete && frameImages[idx + offset].naturalWidth > 0) {
          img = frameImages[idx + offset];
          break;
        }
      }
    }

    if (!img || !img.complete || img.naturalWidth === 0) return;

    currentRenderedIndex = idx;
    const w = canvas.width;
    const h = canvas.height;
    const imgW = img.naturalWidth;
    const imgH = img.naturalHeight;

    const scale = Math.max(w / imgW, h / imgH);
    const renderW = imgW * scale;
    const renderH = imgH * scale;
    const shiftX = (w - renderW) / 2;
    const shiftY = (h - renderH) / 2;

    ctx.drawImage(img, 0, 0, imgW, imgH, shiftX, shiftY, renderW, renderH);
  }

  // Choose asset directory based on screen resolution
  const isMobile = window.innerWidth <= 768 && (window.devicePixelRatio || 1) < 2;
  currentSet = isMobile ? 'm' : 'd';
  const basePath = `/static/media/hero/${currentSet}/`;

  function getFrameUrl(i) {
    const num = String(i + 1).padStart(3, '0');
    return `${basePath}f${num}.webp`;
  }

  function loadImage(i) {
    if (frameImages[i]) return Promise.resolve(frameImages[i]);
    return new Promise((resolve) => {
      const img = new Image();
      img.decoding = 'async';
      img.onload = () => {
        frameImages[i] = img;
        if (i === 0 && currentRenderedIndex < 0) {
          drawFrame(0);
        }
        resolve(img);
      };
      img.onerror = () => resolve(null);
      img.src = getFrameUrl(i);
    });
  }

  // Load first frame and poster immediately
  const poster = new Image();
  poster.src = '/static/media/hero/poster.jpg';
  poster.onload = () => {
    if (currentRenderedIndex < 0) {
      const w = canvas.width;
      const h = canvas.height;
      const scale = Math.max(w / poster.naturalWidth, h / poster.naturalHeight);
      const renderW = poster.naturalWidth * scale;
      const renderH = poster.naturalHeight * scale;
      ctx.drawImage(poster, (w - renderW) / 2, (h - renderH) / 2, renderW, renderH);
    }
  };

  // Eagerly load initial frames (0 to 18)
  const initialLoads = [];
  for (let i = 0; i < 20; i++) {
    initialLoads.push(loadImage(i));
  }

  // Progressively queue remaining frames in background batches
  Promise.all(initialLoads).then(() => {
    let nextIdx = 20;
    function loadBatch() {
      if (nextIdx >= totalFrames) return;
      const batchEnd = Math.min(nextIdx + 10, totalFrames);
      const batch = [];
      for (let i = nextIdx; i < batchEnd; i++) {
        batch.push(loadImage(i));
      }
      nextIdx = batchEnd;
      Promise.all(batch).then(() => {
        if ('requestIdleCallback' in window) {
          window.requestIdleCallback(loadBatch);
        } else {
          setTimeout(loadBatch, 40);
        }
      });
    }
    loadBatch();
  });

  // Initialize GSAP & ScrollTrigger
  if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    const scrubberObj = { frame: 0 };

    const heroTimeline = gsap.timeline({
      scrollTrigger: {
        trigger: scrollContainer,
        start: 'top top',
        end: 'bottom bottom',
        scrub: 0.4,
        onUpdate: (self) => {
          const p = self.progress;
          // Synchronize copy beat active states
          beats.forEach((b, i) => {
            const range = [
              [0.0, 0.22],
              [0.26, 0.48],
              [0.52, 0.73],
              [0.77, 1.0]
            ][i];
            if (range && p >= range[0] && p <= range[1]) {
              b.classList.add('active');
            } else {
              b.classList.remove('active');
            }
          });
        }
      }
    });

    // 1. Scrub frames from 0 to 149
    heroTimeline.to(scrubberObj, {
      frame: totalFrames - 1,
      ease: 'none',
      duration: 1,
      onUpdate: () => {
        const frameIndex = Math.min(totalFrames - 1, Math.max(0, Math.round(scrubberObj.frame)));
        drawFrame(frameIndex);
      }
    }, 0);

    // 2. Synchronize copy beats
    // Beat 0: "B-roll that fits what you say."
    heroTimeline.fromTo(beats[0], 
      { opacity: 1, y: 0 }, 
      { opacity: 0, y: -24, ease: 'power1.in', duration: 0.18 }, 
      0.12
    );

    // Beat 1: "True."
    if (beats[1]) {
      heroTimeline.fromTo(beats[1],
        { opacity: 0, y: 24 },
        { opacity: 1, y: 0, ease: 'power1.out', duration: 0.10 },
        0.24
      );
      heroTimeline.to(beats[1],
        { opacity: 0, y: -24, ease: 'power1.in', duration: 0.10 },
        0.44
      );
    }

    // Beat 2: "Cuts."
    if (beats[2]) {
      heroTimeline.fromTo(beats[2],
        { opacity: 0, y: 24 },
        { opacity: 1, y: 0, ease: 'power1.out', duration: 0.10 },
        0.50
      );
      heroTimeline.to(beats[2],
        { opacity: 0, y: -24, ease: 'power1.in', duration: 0.10 },
        0.70
      );
    }

    // Beat 3: "Yours."
    if (beats[3]) {
      heroTimeline.fromTo(beats[3],
        { opacity: 0, y: 24 },
        { opacity: 1, y: 0, ease: 'power1.out', duration: 0.12 },
        0.75
      );
    }

    // Initial render of frame 0
    drawFrame(0);
  } else {
    // Fallback if GSAP is blocked
    window.addEventListener('scroll', () => {
      const rect = scrollContainer.getBoundingClientRect();
      const totalDist = scrollContainer.offsetHeight - window.innerHeight;
      if (totalDist <= 0) return;
      const progress = Math.min(1, Math.max(0, -rect.top / totalDist));
      const targetFrame = Math.min(totalFrames - 1, Math.floor(progress * totalFrames));
      drawFrame(targetFrame);
    });
  }
})();

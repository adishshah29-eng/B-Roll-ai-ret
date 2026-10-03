/**
 * Epoch Landing Page Interactivity
 * Handles sticky nav styling, real travel-v3c showcase interaction, and smooth anchor scrolling
 */

(function () {
  'use strict';

  // 1. Sticky Navigation Scroll Threshold
  const header = document.querySelector('.site-header');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 40) {
      header?.classList.add('scrolled');
    } else {
      header?.classList.remove('scrolled');
    }
  }, { passive: true });

  // 2. Showcase Project Interactive Slot Switcher
  const showcaseData = [
    {
      index: 0,
      timing: "04.43s – 06.00s",
      anchor: "Rajasthan",
      transcript: "Hi everyone, welcome back to the channel. Today I'm taking you on a week through Rajasthan and the Himalayas.",
      query: "amber fort jaipur",
      reason: "Visualizes the destination of Rajasthan with iconic heritage architecture.",
      shotId: 3976,
      shotTitle: "snow, mountain, range",
      author: "DesignScape",
      source: "Pixabay",
      licence: "Pixabay Content License (Free for commercial use)",
      licenceUrl: "https://pixabay.com/service/license-summary/",
      verdictStatus: "warn",
      verdictLabel: "STOCK · not event footage",
      evidence: [
        "Stock footage (pixabay), not footage of the actual event in Rajasthan",
        "No place evidence in the footage to confirm Rajasthan location",
        "Recording date unknown; cannot confirm it is recent"
      ],
      imageSrc: "/static/media/shots/travel_broll_cut_1.jpg",
      thumbSrc: "/static/media/shots/shot_3976.jpg"
    },
    {
      index: 1,
      timing: "06.00s – 09.12s",
      anchor: "markets",
      transcript: "We will start in the buzzing local bazaars, sampling spices and street foods at sunset...",
      query: "bazaar street spices market",
      reason: "Establishes energetic sensory atmosphere for street food commentary.",
      shotId: 11,
      shotTitle: "Spice Market Vendor",
      author: "Local Archive",
      source: "Local Library",
      licence: "Direct Archive Clearance (Commercial Clean)",
      licenceUrl: "#",
      verdictStatus: "ok",
      verdictLabel: "VERIFIED · Authentic Market",
      evidence: [
        "Visual elements confirm outdoor Indian spice market stalls",
        "Lighting and daylight match transcript evening timing"
      ],
      imageSrc: "/static/media/shots/shot_11.jpg",
      thumbSrc: "/static/media/shots/shot_11.jpg"
    },
    {
      index: 2,
      timing: "09.12s – 12.45s",
      anchor: "train",
      transcript: "Before taking an overnight train crossing the misty valley into the pine ridge.",
      query: "train traveling through mountains",
      reason: "Cuts right on the spoken word 'train' to bridge the narrative journey.",
      shotId: 3584,
      shotTitle: "High Speed Train Mountain Crossing",
      author: "Samsung C9",
      source: "Pixabay",
      licence: "Pixabay Content License (Free for commercial use)",
      licenceUrl: "https://pixabay.com/service/license-summary/",
      verdictStatus: "ok",
      verdictLabel: "VERIFIED · Motion Conforms",
      evidence: [
        "Locomotive crossing elevated mountain terrain matches valley script",
        "Pacing matches 120bpm spoken tempo without audio interruption"
      ],
      imageSrc: "/static/media/shots/travel_broll_cut_2.jpg",
      thumbSrc: "/static/media/shots/shot_3584.jpg"
    },
    {
      index: 3,
      timing: "12.45s – 15.20s",
      anchor: "morning",
      transcript: "Waking up with a steaming hot cup overlooking the snow peaks.",
      query: "coffee, cup, espresso",
      reason: "Intimate pause cut before host resumes dialogue.",
      shotId: 3899,
      shotTitle: "coffee, cup, espresso",
      author: "Engin Akyurt",
      source: "Pixabay",
      licence: "Pixabay Content License (Free for commercial use)",
      licenceUrl: "https://pixabay.com/service/license-summary/",
      verdictStatus: "warn",
      verdictLabel: "STOCK · Illustrative Only",
      evidence: [
        "Indoor ceramic espresso cup; transcript describes outdoor mountain morning",
        "Eligible as atmospheric cut, flag placed in provenance ledger"
      ],
      imageSrc: "/static/media/shots/shot_3899.jpg",
      thumbSrc: "/static/media/shots/shot_3899.jpg"
    }
  ];

  const slotButtons = document.querySelectorAll('.slot-btn');
  const previewImg = document.getElementById('showcase-preview-img');
  const quoteEl = document.getElementById('showcase-quote');
  const anchorTag = document.getElementById('showcase-anchor-tag');
  const verdictBadge = document.getElementById('showcase-verdict-badge');
  const evidenceList = document.getElementById('showcase-evidence-list');
  const shotTitleEl = document.getElementById('showcase-shot-title');
  const shotAuthorEl = document.getElementById('showcase-shot-author');
  const shotLicenceEl = document.getElementById('showcase-shot-licence');
  const shotTimingEl = document.getElementById('showcase-shot-timing');

  function updateShowcase(idx) {
    const d = showcaseData[idx];
    if (!d) return;

    slotButtons.forEach((btn, i) => {
      btn.classList.toggle('active', i === idx);
    });

    if (previewImg) {
      previewImg.src = d.imageSrc;
      previewImg.alt = `Epoch cut preview: ${d.shotTitle}`;
    }

    if (quoteEl) quoteEl.textContent = `“${d.transcript}”`;
    if (anchorTag) anchorTag.textContent = `Anchor: "${d.anchor}"`;

    if (verdictBadge) {
      verdictBadge.textContent = d.verdictLabel;
      verdictBadge.style.color = d.verdictStatus === 'ok' ? 'var(--ok)' : 'var(--warn-dot)';
      const box = verdictBadge.closest('.truth-verdict-box');
      if (box) {
        box.style.borderColor = d.verdictStatus === 'ok' ? 'rgba(42, 117, 83, 0.4)' : 'rgba(184, 123, 25, 0.4)';
        box.style.background = d.verdictStatus === 'ok' ? 'rgba(42, 117, 83, 0.12)' : 'rgba(138, 90, 18, 0.12)';
      }
    }

    if (evidenceList) {
      evidenceList.innerHTML = '';
      d.evidence.forEach(ev => {
        const li = document.createElement('li');
        li.textContent = ev;
        evidenceList.appendChild(li);
      });
    }

    if (shotTitleEl) shotTitleEl.textContent = `${d.shotTitle} (#${d.shotId})`;
    if (shotAuthorEl) shotAuthorEl.textContent = `${d.author} (${d.source})`;
    if (shotLicenceEl) shotLicenceEl.textContent = d.licence;
    if (shotTimingEl) shotTimingEl.textContent = d.timing;
  }

  slotButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.slot, 10);
      updateShowcase(idx);
    });
  });

  // 3. Smooth scrolling for internal anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      if (targetId === '#' || !targetId.startsWith('#')) return;
      const targetEl = document.querySelector(targetId);
      if (targetEl) {
        e.preventDefault();
        targetEl.scrollIntoView({ behavior: 'smooth' });
      }
    });
  });
})();

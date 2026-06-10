// Generates public/og-image.png — the 1200x630 social card for velapwr.com.
// Run with: node scripts/build-og-image.mjs
import sharp from 'sharp';
import { writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const out = resolve(__dirname, '../public/og-image.png');

// The Vela geometric mark, reused from public/favicon.svg (viewBox 418 48 620 544).
const iconInner = `
  <defs>
    <path id="velaIcon" d="M 962 56 L 958 56 L 949 62 L 938 67 L 931 72 L 926 74 L 924 76 L 917 79 L 915 81 L 900 89 L 895 93 L 887 97 L 847 123 L 844 126 L 831 134 L 816 146 L 812 148 L 741 204 L 734 211 L 727 216 L 719 224 L 694 245 L 645 292 L 644 292 L 605 332 L 605 333 L 565 375 L 558 384 L 549 393 L 542 403 L 536 409 L 532 415 L 511 440 L 509 444 L 504 449 L 492 465 L 486 475 L 483 478 L 482 481 L 479 484 L 472 496 L 464 507 L 463 510 L 459 515 L 457 520 L 455 522 L 449 534 L 443 543 L 439 552 L 437 554 L 423 582 L 423 585 L 436 580 L 442 579 L 445 577 L 448 577 L 464 571 L 467 571 L 470 569 L 473 569 L 480 566 L 494 563 L 501 560 L 508 559 L 512 557 L 517 557 L 524 554 L 528 554 L 540 550 L 545 550 L 553 547 L 559 547 L 568 544 L 573 544 L 577 542 L 589 541 L 598 538 L 609 537 L 614 535 L 627 534 L 628 533 L 637 532 L 638 531 L 649 531 L 650 530 L 660 529 L 661 528 L 677 528 L 678 527 L 684 527 L 685 526 L 691 526 L 692 525 L 722 525 L 722 522 L 719 515 L 719 511 L 717 507 L 717 492 L 716 491 L 716 485 L 715 484 L 715 474 L 717 468 L 717 455 L 718 454 L 718 449 L 720 445 L 720 439 L 721 438 L 725 419 L 727 415 L 727 412 L 729 408 L 729 405 L 731 402 L 731 399 L 736 388 L 736 385 L 738 382 L 738 380 L 740 377 L 744 365 L 747 360 L 748 355 L 753 346 L 756 337 L 764 321 L 766 319 L 766 317 L 768 315 L 780 291 L 785 284 L 788 277 L 795 267 L 800 257 L 804 252 L 806 247 L 831 209 L 854 178 L 876 151 L 879 146 L 902 119 L 912 109 L 918 101 L 943 76 L 943 75 L 949 69 L 950 69 L 952 66 L 962 58 Z M 883 189 L 856 225 L 851 234 L 838 253 L 836 258 L 826 274 L 823 281 L 821 283 L 804 318 L 802 325 L 799 330 L 799 332 L 796 337 L 795 342 L 789 355 L 787 363 L 785 366 L 783 374 L 781 377 L 781 380 L 779 383 L 779 386 L 777 389 L 776 395 L 773 402 L 772 409 L 770 413 L 770 417 L 767 425 L 767 429 L 765 433 L 764 443 L 762 447 L 762 454 L 761 455 L 761 460 L 760 461 L 759 473 L 787 491 L 802 502 L 827 523 L 849 545 L 852 546 L 858 546 L 859 547 L 865 547 L 866 548 L 871 548 L 876 550 L 883 550 L 892 553 L 903 554 L 911 557 L 917 557 L 921 559 L 932 560 L 940 563 L 945 563 L 953 566 L 958 566 L 961 568 L 966 568 L 969 570 L 974 570 L 980 573 L 984 573 L 987 575 L 991 575 L 998 578 L 1005 579 L 1028 587 L 1033 587 L 1033 585 L 1030 584 L 1018 576 L 978 546 L 941 510 L 925 489 L 915 474 L 913 469 L 909 464 L 894 435 L 894 433 L 892 431 L 891 426 L 887 418 L 886 413 L 884 410 L 881 401 L 881 398 L 879 395 L 879 391 L 876 384 L 876 381 L 874 376 L 874 372 L 871 364 L 871 358 L 870 357 L 870 352 L 869 351 L 869 346 L 868 345 L 868 317 L 867 316 L 868 263 L 870 258 L 871 243 L 872 242 L 872 238 L 874 233 L 874 227 L 875 226 L 875 223 L 878 214 L 878 210 L 882 199 L 882 196 L 884 193 L 884 189 Z" fill-rule="evenodd"/>
    <clipPath id="velaIconClip"><use href="#velaIcon"/></clipPath>
    <linearGradient id="velaBlue" x1="0%" y1="90%" x2="70%" y2="10%"><stop offset="0%" stop-color="#258AE8"/><stop offset="100%" stop-color="#0C6DCC"/></linearGradient>
  </defs>
  <use href="#velaIcon" fill="url(#velaBlue)"/>
  <g clip-path="url(#velaIconClip)">
    <polygon points="420,586 650,290 728,527" fill="#2F8DE2"/>
    <polygon points="650,290 966,56 792,372" fill="#0A67C1"/>
    <polygon points="650,290 792,372 804,468" fill="#0A4198"/>
    <polygon points="420,586 728,527 804,468" fill="#1768D9"/>
    <polygon points="792,372 888,188 882,438" fill="#7AB8F4"/>
    <polygon points="882,438 1036,586 804,468" fill="#2577D9"/>
    <polygon points="804,468 1036,586 728,527" fill="#083891"/>
    <polygon points="882,438 888,188 966,320" fill="#4B95F0" opacity="0.65"/>
  </g>`;

const sans = "Geist, 'Helvetica Neue', Helvetica, Arial, sans-serif";
const mono = "'Geist Mono', 'SF Mono', Menlo, monospace";

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#F8FAFD"/>
      <stop offset="100%" stop-color="#E9EFF8"/>
    </linearGradient>
    <radialGradient id="glow" cx="88%" cy="14%" r="55%">
      <stop offset="0%" stop-color="#1A74D8" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#1A74D8" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#258AE8"/>
      <stop offset="100%" stop-color="#0C4D8C"/>
    </linearGradient>
  </defs>

  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect width="1200" height="630" fill="url(#glow)"/>

  <!-- header: mark + wordmark -->
  <svg x="80" y="68" width="88" height="77" viewBox="418 48 620 544">${iconInner}</svg>
  <text x="186" y="132" font-family="${sans}" font-size="56" font-weight="800" fill="#15181B" letter-spacing="-1">Vela</text>

  <!-- eyebrow -->
  <text x="82" y="252" font-family="${mono}" font-size="22" font-weight="600" fill="#1A74D8" letter-spacing="4">BATTERY&#160;DISPATCH&#160;INTELLIGENCE</text>

  <!-- headline -->
  <text x="80" y="338" font-family="${sans}" font-size="74" font-weight="800" fill="#15181B" letter-spacing="-2">The neutral dispatch layer</text>
  <text x="80" y="422" font-family="${sans}" font-size="74" font-weight="800" fill="#15181B" letter-spacing="-2">for every fleet</text>

  <!-- subhead -->
  <text x="82" y="486" font-family="${sans}" font-size="27" font-weight="500" fill="#5C6167">One explainable MILP solve over market revenue, live degradation, and</text>
  <text x="82" y="522" font-family="${sans}" font-size="27" font-weight="500" fill="#5C6167">your constraints, handed to whatever EMS you already run.</text>

  <!-- footer url -->
  <text x="1118" y="566" text-anchor="end" font-family="${mono}" font-size="24" font-weight="500" fill="#9AA0A6">velapwr.com</text>

  <!-- accent bar -->
  <rect x="0" y="624" width="1200" height="6" fill="url(#bar)"/>
</svg>`;

writeFileSync(resolve(__dirname, '../public/og-image.svg.tmp'), svg);

await sharp(Buffer.from(svg))
  .png({ compressionLevel: 9 })
  .toFile(out);

console.log('Wrote', out);

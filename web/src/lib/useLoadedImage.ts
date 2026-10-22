import { useEffect, useState } from "react";

/**
 * Whether `src` has finished loading, fetched off-screen first.
 *
 * For images the platforms may not have: a CDN answers for most players and
 * 404s for the rest, and an `<img>` put on the page to find out shows its
 * empty frame until the failure comes back. Asking first means a missing
 * image is never drawn at all, rather than drawn and then taken away.
 *
 * Compared against the `src` that loaded rather than reset on change, so a
 * different player's photo is never shown under the next one's name.
 */
export function useLoadedImage(src: string): boolean {
  const [loaded, setLoaded] = useState<string | null>(null);

  useEffect(() => {
    if (!src) return;
    let live = true;
    const image = new Image();
    image.onload = () => {
      if (live) setLoaded(src);
    };
    image.src = src;
    return () => {
      live = false;
      image.onload = null;
    };
  }, [src]);

  return Boolean(src) && loaded === src;
}

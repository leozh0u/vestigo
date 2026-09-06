/*
  The numbers the two halves of the zoom have to agree on.

  The intro is one continuous fall rendered by two different things: a textured
  sphere from three and a half Earth radii down to three thousand kilometres,
  and Google's photogrammetry from there to a street. They are joined by a
  quarter-second dissolve, and for that join to disappear the two have to be
  photographing the same place, at the same scale, in the same light, at the
  same speed, with the same amount of detail in the frame. Each of those was
  wrong once and each was fixed separately.

  Scale was the last and the worst, because the fix for it is not a constant, it
  is a shared curve. During the overlap the dissolve pairs the globe's frame at
  time T with the tiles' frame at T minus the offset, and it was pairing 3,645
  km with 3,000, then 3,427 with 2,656, then 3,000 with 2,084. Twenty-one per
  cent apart at the start of the blend and forty-four at the end: the two images
  never once agreed on how big anything was, so every overlapped frame was a
  coastline drawn twice at two different sizes. That is what reads as the
  picture jumping, and it cannot be tuned away on either side alone.

  So the fall belongs here, in one file, and the globe's last quarter second
  runs the tiles' own curve. Not an approximation of it, the same function.
  After that the blend is pairing identical framings and has nothing left to do
  except swap one source of pixels for another.
*/

export const HANDOVER = {
  // Where the tiles pick up the fall, in metres above the ellipsoid, and where
  // the globe's dive therefore has to end. Three thousand rather than six
  // hundred because Blue Marble is 7.4 km a pixel: at six hundred the globe is
  // showing about fifty texture pixels across the frame, which no amount of
  // matching makes look like a photograph. At three thousand it is showing
  // three hundred.
  top: 3000000,
  // Eighty metres above the street. Lower than that and the photogrammetry
  // melts: brick drips and windows become smears. Demonstrated across eighteen
  // candidate endings before settling here.
  end: 80,
  /*
    Length of the descent, seconds.

    Twelve rather than nine, and the reason is the turn at the end. The shot has
    to pitch ninety degrees from looking straight down to level with a window,
    and it is only allowed to do that once it is nearly there — turning at two
    hundred metres is what made the old ending read as a fly-over. At nine
    seconds the last fifth is 1.5 s, which is sixty degrees a second and
    measured as a whip: four times the surrounding motion, on a shot that is
    already moving fast because the camera is among buildings.

    The altitudes the turn spans are unchanged, about eighty-five metres down to
    seventeen. There is simply more time to cross them, because the fall is
    logarithmic and stretching the shot stretches the bottom of it most.
  */
  seconds: 12,
  // Overlap at the seam. Short, because it is no longer hiding anything.
  fade: 0.10,
};

/*
  Height above the street at a point through the descent, metres.

  Log space, so a constant ratio of altitude goes by per second, which is what
  reads as a zoom rather than as a drop. Eased out only: an ease-in has zero
  slope at zero, and when this was ease-in-out the opening thirty-four frames
  changed by almost nothing and then the middle lurched to catch up. Past about
  1.6 the tail decelerates to a standstill and the stall returns at the other
  end.
*/
export function fallHeight(t, endHeight = HANDOVER.end) {
  const fall = 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 1.25);
  return Math.exp(Math.log(HANDOVER.top) +
                  (Math.log(endHeight) - Math.log(HANDOVER.top)) * fall);
}

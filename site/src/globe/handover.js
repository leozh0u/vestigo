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
  /*
    Fifty-five metres above the street, and it used to be sixteen.

    Sixteen put the camera level with a fifth-floor window, which is the shot
    this was designed around, and the shot cannot be had: measured off the
    finished file, the last four and a half seconds are unusable. At eleven
    seconds in, twenty-seven metres up, the frame is melted brick and smeared
    windows, because Google's photogrammetry below about forty metres has no
    data to reconstruct from. Everything after that was a hand-built facade and
    room, which is worse again -- flat tiling brick and black rectangles for the
    neighbours' windows.

    A hundred and fifty is where it still holds up, and getting to that number
    took three passes of probe frames. Fifty-five was the first guess and it is
    wrong for a reason worth writing down: the fall lands over a tree-lined
    street, and Google reconstructs a tree canopy as dark blobs. At a hundred
    and fourteen metres the frame was blobs. At two hundred it was legible
    rooftops, cars and kerbs, sharp.

    So the shot ends at a hundred and fifty and goes to black, and what happens
    indoors is a photograph rather than a guess.
  */
  end: 150,
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
  /*
    Ten point four, and there is no longer a turn to level at the end of it.

    The fifteen seconds were fifteen because the shot had to pitch ninety
    degrees and then fly at a window, and it had to do the pitch late or it read
    as a fly-over. Neither happens now: the shot stops at fifty-five metres,
    where the camera is still above every roof, and the pitch only comes round
    far enough to put the street ahead in frame.

    Five and a half seconds shorter, and all of it came out of the part nobody
    could stand to look at.
  */
  seconds: 9.4,
  /*
    How much of that is the fall, seconds.

    The last two seconds are not a fall, they are a push: the camera is already
    level with a fifth-floor window and flies at it. Keeping the fall's own
    length fixed at twelve while the shot grows to fourteen means the rate it
    hands over at is unchanged, so the globe's dive does not have to be retuned
    a third time — that rate is set by how fast the fall starts, and the fall is
    the same fall.
  */
  /*
    All of it. The shot is a fall now and nothing else.

    This used to be shorter than `seconds`, because the last two seconds were a
    horizontal push at a window rather than a descent. There is no push, so the
    two are the same number and place() has no second phase -- which is also why
    it is still a separate field: the fall's rate at the top is set by this, and
    that rate is what the Earth beat's dive has to hand over at.
  */
  fallSeconds: 9.4,
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

-- FlickPick Initial Data Setup
-- Run these statements to populate the database with sample data

-- ============================================================================
-- USERS
-- ============================================================================
INSERT INTO users (id, name, email, created_at) VALUES
  (1, 'Priya Nair', 'priya@flickpick.example', now()),
  (2, 'Marcus Webb', 'marcus@flickpick.example', now()),
  (3, 'Sofia Alvarez', 'sofia@flickpick.example', now()),
  (4, 'Dan Ochieng', 'dan@flickpick.example', now())
ON CONFLICT (email) DO NOTHING;

-- Reset the users ID sequence
SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));

-- ============================================================================
-- GROUPS
-- ============================================================================
INSERT INTO groups (id, name, created_at) VALUES
  (1, 'Friday Night Crew', now()),
  (2, 'Sunday Doc Club', now())
ON CONFLICT (id) DO NOTHING;

-- Reset the groups ID sequence
SELECT setval('groups_id_seq', (SELECT MAX(id) FROM groups));

-- ============================================================================
-- GROUP MEMBERS
-- ============================================================================
INSERT INTO group_members (group_id, user_id, joined_at) VALUES
  -- Friday Night Crew (all 4 members)
  (1, 1, now()),
  (1, 2, now()),
  (1, 3, now()),
  (1, 4, now()),
  -- Sunday Doc Club (Priya and Sofia)
  (2, 1, now()),
  (2, 3, now())
ON CONFLICT (group_id, user_id) DO NOTHING;

-- ============================================================================
-- MOVIES (from TMDB)
-- ============================================================================
INSERT INTO movies (id, title, poster_path, release_date, overview, created_at) VALUES
  (101, 'Parasite', '/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg', '2019-05-30', 
   'Greed and class discrimination threaten the newly formed symbiotic relationship between the wealthy Park family and the destitute Kim clan.', now()),
   
  (102, 'Everything Everywhere All at Once', '/w3LxiVYdWWRvEVdn5RYq6jIqkb1.jpg', '2022-03-24',
   'An aging Chinese immigrant is swept up in an insane adventure, where she alone can save the world by exploring other universes.', now()),
   
  (103, 'Spirited Away', '/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg', '2001-07-20',
   'A young girl wanders into a world ruled by gods and witches, where humans are changed into beasts.', now()),
   
  (104, 'Dune', '/d5NXSklXo0qyIYkgV94XAgMIckC.jpg', '2021-10-22',
   'A noble family becomes embroiled in a war for control over the galaxy''s most valuable asset while its heir becomes troubled by visions of a dark future.', now()),
   
  (105, 'The Grand Budapest Hotel', '/nX5XiO9m3E0PLAMTHZFN0GEwiOm.jpg', '2014-02-26',
   'The adventures of Gustave H, a legendary concierge, and Zero Moustafa, the lobby boy who becomes his most trusted friend.', now()),
   
  (106, 'Oldboy', '/pWDtjs568ZfOTMbURQBYuT4Qxka.jpg', '2003-11-21',
   'After being kidnapped and imprisoned for fifteen years, Oh Dae-Su is released, only to find that he must find his captor in five days.', now()),
   
  (107, 'Whiplash', '/6uSPcdGNA2A6vJmCagXkvnutegs.jpg', '2014-10-10',
   'A promising young drummer enrolls at a cut-throat music conservatory where his dreams of greatness are mentored by an instructor who will stop at nothing.', now()),
   
  (108, 'Coco', '/gGEsBPAijhVUFoiNpgZXqRVWJt2.jpg', '2017-10-27',
   'Aspiring musician Miguel enters the Land of the Dead to unlock the real story behind his family''s ancient ban on music.', now())
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- WATCHLIST
-- ============================================================================
INSERT INTO watchlist (id, group_id, movie_id, added_by_user_id, created_at, watched_at) VALUES
  -- Queued movies (watched_at is NULL)
  (1, 1, 104, 2, '2026-08-01', NULL),  -- Dune, added by Marcus
  (2, 1, 105, 3, '2026-08-03', NULL),  -- The Grand Budapest Hotel, added by Sofia
  
  -- Already watched movies
  (3, 1, 101, 1, '2026-07-20', '2026-07-26'),  -- Parasite, watched
  (4, 1, 106, 4, '2026-07-10', '2026-07-15')   -- Oldboy, watched
ON CONFLICT (group_id, movie_id) DO NOTHING;

-- Reset the watchlist ID sequence
SELECT setval('watchlist_id_seq', (SELECT MAX(id) FROM watchlist));

-- ============================================================================
-- RATINGS (1-5 scale)
-- ============================================================================
INSERT INTO ratings (movie_id, user_id, rating, created_at) VALUES
  -- Parasite (101) — loved by group 1, avg = 4.75
  (101, 1, 5, now()),
  (101, 2, 5, now()),
  (101, 3, 4, now()),
  (101, 4, 5, now()),
  
  -- Oldboy (106) — disliked by group 1, avg = 1.75
  (106, 1, 2, now()),
  (106, 2, 1, now()),
  (106, 3, 2, now()),
  (106, 4, 2, now())
ON CONFLICT (movie_id, user_id) DO NOTHING;

-- ============================================================================
-- RECOMMENDATIONS (per-user movie recommendations)
-- ============================================================================
INSERT INTO recommendations (user_id, movie_id, score, reason, created_at) VALUES
  (1, 102, 92.4, 'Because you loved Parasite''s genre-bending tone', now()),
  (2, 102, 88.1, 'Trending with friends who liked Sci-Fi/Comedy', now()),
  (3, 103, 85.0, 'Matches your high ratings for animated features', now()),
  (4, 108, 79.3, 'Similar warmth and score to Coco''s genre peers', now()),
  (1, 107, 74.5, 'High popularity among users with your rating history', now())
ON CONFLICT DO NOTHING;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these to verify data was inserted correctly:

-- SELECT * FROM users;
-- SELECT * FROM groups;
-- SELECT * FROM group_members;
-- SELECT * FROM movies;
-- SELECT * FROM watchlist;
-- SELECT * FROM ratings;
-- SELECT * FROM recommendations;

-- Check group 1's watchlist with movie details:
-- SELECT w.*, m.title, m.overview, m.poster_path
-- FROM watchlist w
-- JOIN movies m ON w.movie_id = m.id
-- WHERE w.group_id = 1
-- ORDER BY w.watched_at NULLS FIRST, w.created_at DESC;

-- Check average ratings per movie for group 1:
-- SELECT m.title, 
--        COUNT(r.rating) as rating_count,
--        AVG(r.rating)::numeric(3,2) as avg_rating
-- FROM movies m
-- JOIN ratings r ON m.id = r.movie_id
-- JOIN group_members gm ON r.user_id = gm.user_id
-- WHERE gm.group_id = 1
-- GROUP BY m.id, m.title
-- ORDER BY avg_rating DESC;

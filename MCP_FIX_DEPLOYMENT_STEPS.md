
╔══════════════════════════════════════════════════════════════════════════════╗
║                  🔧 FIX MCP SERVER 404 ERROR - ACTION PLAN                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

The error keeps happening because:
  ❌ Your DEPLOYED app still has the old code (HTTP transport)
  ❌ Your REGISTERED URL is missing /sse

The fix IS in your code, but needs to be deployed!

════════════════════════════════════════════════════════════════════════════════
STEP 1: Redeploy the MCP Server with Fixed Code
════════════════════════════════════════════════════════════════════════════════

Open a terminal and run these commands:

cd /Workspace/Users/abel.johny@proton.me/FlickPick/mcp_server

# Redeploy with the SSE transport fix
databricks apps deploy flickpick-mcp --source-code-path .

# Wait 30-60 seconds for deployment

# Check status (should show "state": "RUNNING")
databricks apps get flickpick-mcp

# View logs to confirm SSE transport
databricks apps logs flickpick-mcp --tail 50


EXPECTED IN LOGS:
✓ "Started server on 0.0.0.0:8000 with SSE transport"
✓ "Application startup complete"


════════════════════════════════════════════════════════════════════════════════
STEP 2: Update the Registered MCP Server URL
════════════════════════════════════════════════════════════════════════════════

1. Go to Databricks Workspace Settings (gear icon, top right)
2. Navigate to: AI/ML → MCP Servers
3. Find your MCP server entry (might be named "mcp-server-flickpick" or 
   "FlickPick Movie Tools")
4. Click EDIT
5. Change the URL:

   FROM (wrong):
   https://<workspace>.cloud.databricks.com/apps/flickpick-mcp
   
   TO (correct):
   https://<workspace>.cloud.databricks.com/apps/flickpick-mcp/sse
                                                                ^^^^
                                                         Add this part!

6. Click SAVE


════════════════════════════════════════════════════════════════════════════════
STEP 3: Test the Fixed MCP Server
════════════════════════════════════════════════════════════════════════════════

After redeploying and updating the URL:

# Test the SSE endpoint (should return event-stream, not 404)
curl -H "Accept: text/event-stream" \
  https://<workspace>.cloud.databricks.com/apps/flickpick-mcp/sse


════════════════════════════════════════════════════════════════════════════════
STEP 4: Verify in AI/ML Playground
════════════════════════════════════════════════════════════════════════════════

1. Open Databricks AI/ML Playground (Assistant)
2. The 404 error should be GONE
3. You should see 6 FlickPick tools available:
   - search_and_recommend
   - compare_multiple_movies
   - add_movie_to_watchlist
   - record_movie_rating
   - get_group_watchlist
   - get_group_watched_movies

4. Test with: "Search for action movies for my friends group"


════════════════════════════════════════════════════════════════════════════════
WHY THIS IS HAPPENING
════════════════════════════════════════════════════════════════════════════════

Timeline:
1. ✅ We FIXED the code (changed HTTP → SSE transport)
2. ✅ We COMMITTED and PUSHED to GitHub
3. ❌ BUT the live app is still running the OLD deployment
4. ❌ AND your registered URL doesn't have /sse

Think of it like this:
  - Your SOURCE CODE has the fix (✓)
  - Your DEPLOYED APP doesn't have it yet (needs redeploy)
  - Your REGISTERED URL is pointing to wrong endpoint (needs /sse)

Both need to be updated for it to work!


════════════════════════════════════════════════════════════════════════════════
QUICK REFERENCE COMMANDS
════════════════════════════════════════════════════════════════════════════════

# Redeploy
cd /Workspace/Users/abel.johny@proton.me/FlickPick/mcp_server && \
  databricks apps deploy flickpick-mcp --source-code-path .

# Check status
databricks apps get flickpick-mcp

# View logs
databricks apps logs flickpick-mcp --tail 50

# Test endpoint (replace <workspace> with your actual workspace URL)
curl -H "Accept: text/event-stream" \
  https://<workspace>.cloud.databricks.com/apps/flickpick-mcp/sse


════════════════════════════════════════════════════════════════════════════════
AFTER YOU COMPLETE THESE STEPS
════════════════════════════════════════════════════════════════════════════════

The MCP tools will work! You'll be able to:
  ✓ "Search for sci-fi movies for my group"
  ✓ "Compare Inception and Interstellar"  
  ✓ "Add Blade Runner to my watchlist"
  ✓ "Show me what my friends group has watched"

All 6 FlickPick tools will appear in the AI/ML Playground! 🎬

════════════════════════════════════════════════════════════════════════════════

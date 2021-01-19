import uuid
from flask import Flask, request, jsonify
import threading
import time
from bs4 import BeautifulSoup
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse
import concurrent.futures

# Creates the Flask app
app = Flask(__name__)
# the lock variable to allow threads to modify the list safely
synclock = threading.Semaphore(1)

# the metadata for jobs, including results
jobs = {}

# Validates if the URL is valid. It fails if it's a malformed URL, or if it points to some file types
# Could be done better if we were to check MIME types (assuming webserver provides them correctly)
def validate_url(url):
  try:
    result = urlparse(url)
    return True
  except:
    return False

# The function that will read an HTML page, returning the abolute links and images list
def process_page(url):
  # Uses a header to look like a web browser and read the page source at URL
  hdr = {'User-Agent':'Mozilla/5.0'}
  req = Request(url, headers=hdr)
  response = urlopen(req)
  data = response.read()
  # creates a BeautifulSoup object, using the lxml parser
  soup = BeautifulSoup(data, 'lxml')
  
  # Retrieves the links from the soup object, retriving them from the anchor tags 
  # Also, uses urljoin to get absolute links from relative ones
  links=[]
  for link in set(soup.findAll('a')):
    newurl=urljoin(url,link.get('href'))
    if validate_url(newurl):
      links.append(newurl)
  images=[]
  # Retrieves the images, but from img tags - file is described in the srg attribute
  # Also uses urljoin to get absolute links for the images that are relative locations
  for img in set(soup.findAll('img')):
    images.append(urljoin(url,img['src']))

  # Returns the links and images as a tuple
  return links,images


# The thread function, which is 
def crawling_thread(num, jobid):

  # Booelan value that says the thread need to run. 
  # Set to false when there are no more URLs to parse (list in the job meta data)
  run = True
  while run:
    # Retrieves the next page to process, if empty, may need to wait until
    # pages being processed are completed (may add more URLs)
    next = ""
    # The key "crawler_lock" is used as a semaphor and avoid concurrent 
    # coarse grained modifications to lists
    synclock.acquire()
    # If there is a todo URL, retrieves it and move it to the processing list
    if len(jobs[jobid]['todo']) > 0:
      next = jobs[jobid]['todo'].popitem()
      jobs[jobid]['processing'].append(next[0])
    synclock.release()
    # If we were able to get an URL to process, we crawl it
    if next != "":
      app.logger.info(" %s - Thread %d crawling %s (level %d)" % (jobid, num, next[0], next[1]))
      [links, images]=process_page(next[0])
      # The next block will remove the URL from the pages being processed list
      # and stores the reults in the meta data
      synclock.acquire()
      jobs[jobid]['processing'].remove(next[0])
      jobs[jobid]['results'][next[0]]=images
      # Here we calculate the next depth level when following links
      # If below the maximum value, we add them to the "todo" list in the metadata
      nextlevel = next[1]+1
      if nextlevel<jobs[jobid]['maxlevels']:
        for l in links:
          jobs[jobid]['todo'][l]=nextlevel
      synclock.release()
    # if all links to process are taken, we need to wait for new links
    # the reason is because the last link may add more pages to crawl. 
    # If not empty,the thread waits one second
    elif len(jobs[jobid]['processing'])>0:
      time.sleep(1)
    # othewise, there are no more pages processing, we're done!
    else:
      run=False
  return num

# This is the function that is used by Redis/rq to run the actual job in the queue
# it takes as input the list of URLs, the number of threads and the maximum depth
# to follow links
def crawling_job(jobid, threads):
  app.logger.info(" %s - Starting crawling job" % (jobid))
  # Creates a thread pool and wait for them to end
  for i in range(threads):
    with concurrent.futures.ThreadPoolExecutor() as executor:
      futures = []
      for i in range(threads):
        futures.append(executor.submit(crawling_thread, i, jobid))
      for future in concurrent.futures.as_completed(futures):
        num = future.result()
        app.logger.info("%s - Thread %d is done" % (jobid, num))

  jobs[jobid]["end"]= time.time()
  jobs[jobid]["finished"] = True
  app.logger.info(" %s - Job completed in %f seconds" % (jobid, jobs[jobid]["end"]-jobs[jobid]["start"]))
  # Instead of returning from the thread here, we do a bit of garbage collection
  # The job IS DONE, and results are available
  # But we wait some time to remove the results and avoid them being there forever
  time.sleep(600)
  synclock.acquire()
  jobs.pop(jobid)
  synclock.release()
  app.logger.info(" %s - Remove job metadata (timeout)" % (jobid))

# Flask callback function to display the job status
# Uses part of the URL to retrive the ID
@app.route("/status/<jobid>")
def jobstatus(jobid):
  if jobid in jobs:
    # the completed pages is the length of the 'results' dictionary in the metadata
    completed = len(jobs[jobid]['results'])
    # in progress pages is the length of the 'todo' list and 'processing' lists
    inprogress = len(jobs[jobid]['todo'])+len(jobs[jobid]['processing'])
    return ('{"completed": %d, "inprogress": %d}\n' % (completed, inprogress))
  else:
    return('{"Error"}')

# Flask callback function to show the results, the job ID is part of the URL
@app.route("/result/<jobid>")
def jobresult(jobid):
  if jobid in jobs:
    # ifthe job is finished, show the results
    if jobs[jobid]["finished"]:
      return jobs[jobid]['results']
    # Otherwise, returns the current status
    else:
      return '{"Wait"}\n'
  else:
    return '{"Job not found"}\n'

# Flask call back function to queue a new job
# The parameters are passed in a JSON object whith can have the following nodes:
#
# - urls: list of URLs to start crawling from (mandatory)
# - threads: the number of threads (integer, optional)
# - levels: the number of page levels fo crawl
@app.route("/", methods=['POST'])
def index():

  # Retrieves the data from the JSON input in the POST request
  data = request.get_json()
  
  # By default, we use only one thread and go down only one level
  threads = 1
  levels = 2
  # Retrieve the number of threads and levels to crawl
  if 'threads' in data:
    threads = int(data.get('threads',0))
  if 'levels' in data:
    levels = int(data.get('levels',0))
  urls=[]
  # Retrieve the URL list, which is MANDATORY
  if 'urls' in data:
    urls = list(set(data.get('urls',0)))
  else:
    return jsonify({ 'error': 'Missing url list node' }), 400
  
  # If we have at least the URL list, creates the job
#  job = q.enqueue(crawling_job, urls, threads, levels)

  jobid = str(uuid.uuid4())
  # Prepares the metadata for the job
  jobs[jobid]={}
  # the URLs that need to be crfawled, all startig at level 0 (first level)
  jobs[jobid]["todo"]={}
  for url in urls:
    jobs[jobid]["todo"][url]=0
  # The URLs under processing (to keep tracking that we still are working)
  jobs[jobid]["processing"]=[]
  # The completed URLs
  jobs[jobid]["results"]={}
  # finally, the timestamp used to control when the job results should be removed
  jobs[jobid]["start"]=time.time()
  jobs[jobid]["end"]=0
  # The levels to follow
  jobs[jobid]["maxlevels"]=levels
  jobs[jobid]["finished"]=False

  job = threading.Thread(target=crawling_job, args=(jobid, threads))
  job.start()

  return ("{\"job_id\":\"%s\",\"threads\":\"%d\",\"urls\":\"%s\"}\n" % (jobid, threads,urls)), 200

# Error handlers
@app.errorhandler(400)
def internal_error(error):
    return '{"error": 400, "text": "Bad request"}',400

@app.errorhandler(403)
def internal_error(error):
    return '{"error": 403, "text": "Forbidden"}',403

@app.errorhandler(404)
def not_found_error(error):
    return '{"error": 404, "text": "Page not found"}', 404
 
@app.errorhandler(500)
def internal_error(error):
    return '{"error": 500, "text": "Internal server error"}',500

# Will only run the Flask app if this is the main module
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)


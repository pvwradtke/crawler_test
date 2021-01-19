# crawler_test
Project to try out Flask and Docker to make a containerized web crawler that search for images links inside web pages and their linked pages (2 levels of depth).

For complete details, please see the file webcrawler_white_paper.pdf.

After checking out the project, build it with:

  docker build -t crawler_test -f Dockerfile ./
  
All requirements are included in the requirements.txt file. Once built, please run with:

  docker run -p 8080:8080 crawler_test
  
This will launch Flask and run the web API service. To access it, please send a fully formed JSON document as a parameter in the index page. For instance:


  curl -X POST 'http://127.0.0.1:8080' -H "Content-Type: application/json" --data '{"urls": ["http://4chan.org/","https://golang.org/"], "threads": 4}'
  
Where "urls" is the list of starting point URLs, and "threads" is the optional number of concurrent threads to use to crawl the webpages - this number is per crawling job, where each crawling job is also a thread. This returns some data, including the process UUID:

  {"job_id":"1ec8fff7-3a1f-41db-8ef7-7c4e6f452cc0","threads":"4","urls":"['https://golang.org/', 'http://4chan.org/']"}

To retrieve the current status for a given job UUID, please use the status page:

   curl 'http://127.0.0.1:8080/status/1ec8fff7-3a1f-41db-8ef7-7c4e6f452cc0'

This returns a list of completed page crawls, and the number of pages to be crawled. Please not that, depending on the pages to crawl, the number may grow (if the crawler finds more pages).

  {"completed": 80, "inprogress": 32}

Once the job is complete, the "inprogress" field will be equal to 0:

  {"completed": 112, "inprogress": 0}
  

Finally, to retrieve the results from a job that complete, please use the result page:

  curl 'http://127.0.0.1:8080/result/1ec8fff7-3a1f-41db-8ef7-7c4e6f452cc0'
  
This will provide a message asking to wait if the job didn't finish, or a list of pages and images found on those pages:

{
  "http://4chan.org/": [
    "http://i.4cdn.org/v/1611007947515s.jpg", 
    "http://i.4cdn.org/vrpg/1610947985169s.jpg", 
    ...
    "http://s.4cdn.org/image/fp/logo-transparent.png", 
    "http://i.4cdn.org/sci/1610900463796s.jpg"
  ], 
  "http://4chan.org/4channews.php": [
    "http://s.4cdn.org/image/news/Happybirthday_17th_th.jpg", 
    "http://s.4cdn.org/image/fp/logo-transparent.png"
  ], 
  "http://4chan.org/advertise": [
    "http://s.4cdn.org/image/fp/logo-transparent.png", 
    ...
    "http://s.4cdn.org/image/advertise/top_ad_desktop.png", 
    "http://s.4cdn.org/image/advertise/top_ad_mobile.png"
  ], 
  "http://4chan.org/contact": [
    "http://s.4cdn.org/image/fp/logo-transparent.png"
  ], 
  ...

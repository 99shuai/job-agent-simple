'''用于过滤不符合条件的职位信息'''
def filter_job(job_list, keyword):
    filtered_jobs = []
    for job in job_list:
        title = job.get('title', '').lower()
        snippet = job.get('snippet', '').lower()
        if keyword.lower() in title or keyword.lower() in snippet:
            filtered_jobs.append(job)
    return filtered_jobs
import os
import re
import time
import random
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from tqdm import tqdm

def fetch_conference_papers(url, list_selector='dt.ptitle a'):
    """
    从会议网页抓取论文标题及其详情页链接。

    Args:
        url (str): 会议论文列表页面的 URL。
        list_selector (str): CSS 选择器，用于定位列表中的标题链接元素。
                             CVF Open Access 通常是 'dt.ptitle a'。

    Returns:
        list[dict]: 包含 'title' 和 'link' 的字典列表。
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print(f"Accessing conference papers list page: {url}")
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        elements = soup.select(list_selector)
        
        papers = []
        for el in elements:
            title_text = el.get_text().strip().replace('\n', ' ')
            # 获取相对链接或绝对链接
            href = el.get('href')
            
            if title_text and href:
                # 将相对路径转换为绝对路径
                full_link = urljoin(url, href)
                papers.append({
                    'title': title_text,
                    'link': full_link
                })
                
        print(f"Fetched {len(papers)} papers in total (unfiltered)")
        return papers

    except requests.exceptions.RequestException as e:
        print(f"Failed when fetching conference papers: {e}")
        return []

def filter_papers(papers, regex_pattern):
    """
    根据正则表达式过滤论文列表。
    """
    pattern = re.compile(regex_pattern, re.IGNORECASE)
    matched_papers = [p for p in papers if pattern.search(p['title'])]
    print(f"Filtered {len(matched_papers)} papers whose title contains keyword pattern: '{regex_pattern}'")
    return matched_papers

def get_paper_details_from_page(paper_url):
    """
    访问论文详情页，抓取作者和摘要。
    
    针对 CVF Open Access (openaccess.thecvf.com) 的结构优化：
    - 作者通常在 <div id="authors"> 或 <div id="content"> 下的 <i> 标签
    - 摘要通常在 <div id="abstract">
    """
    def get_thecvf(soup):
        ## Authors
        authors_div = soup.select_one('#authors')
        if authors_div:
            authors = authors_div.get_text().strip()
            authors = authors.replace(';', ',').replace('\n', ' ')
        else:
            authors = "Authors not found"

        ## Abastract
        abstract_div = soup.select_one('#abstract')
        if abstract_div:
            abstract = abstract_div.get_text().strip()
        else:
            abstract = "Abstract not found"

        return {
            'authors': authors,
            'abstract': abstract
        }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(paper_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        if "thecvf" in paper_url.lower():
            return get_thecvf(soup)
        else:
            raise NotImplementedError(f"Unavailable conference url: {paper_url}")

    except Exception as e:
        print(f"Error occured when fetching paper details:\n{e}")
        return {
            'authors': 'Error',
            'abstract': 'Error'
        }

def main():
    import json
    import argparse
    from datetime import datetime

    run_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--conf", type=str, required=True, help="Supported: iccv, cvpr")
    parser.add_argument("-y", "--year", type=str, default="2025")
    parser.add_argument("-i", "--input", type=str, default=None, help="The exported list of a certain conference's accepted papers (json format)")
    parser.add_argument("-s", "--search", type=str, required=True, help="Keywords for search. Regex supported, e.g., \"(transformer|llm|language model)\"")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output file of final results, with the title, url, authors, abs of each paper")

    args = parser.parse_args()
    
    ## Get all papers list
    if args.input is None:
        if args.conf.lower() in ('iccv', 'cvpr'):
            conference_url = f"https://openaccess.thecvf.com/{args.conf.upper()}{args.year}?day=all" 
            list_selector = "dt.ptitle a" 
            # search_regex = r"(effect|small|effic)"
        else:
            raise NotImplementedError(f"Srapper for conference {args.conf} has not been implemented")
        
        all_papers = fetch_conference_papers(conference_url, list_selector)

        with open(f"all_papers_{args.conf}_{args.year}_{args.search}_{run_time}.json", mode='w', encoding='utf-8') as f:
            f.write(json.dumps(all_papers, ensure_ascii=False, indent=4))
    
    else:
        with open(args.input, 'r', encoding='utf-8') as f:
            all_papers = json.loads(f.read())
    
    if not all_papers:
        print("0 papers found, abort")
        return

    ## Filter target papers
    search_regex = args.search
    target_papers = filter_papers(all_papers, search_regex)

    import pdb; pdb.set_trace()

    ## Prepare output path
    output = args.output
    if output is None:
        output = f"paper_result_{args.conf}_{args.year}_{args.search}_{run_time}.json"
    output_jsonl = output + 'l'
    
    ## Get detailed info on target papers
    results = []
    for i, paper in tqdm(enumerate(target_papers), desc="Get paper full info", total=len(target_papers)):
        details = get_paper_details_from_page(paper['link'])
        
        full_info = {
            'title': paper['title'],
            'url': paper['link'],
            'authors': details['authors'],
            'abstract': details['abstract']
        }
        results.append(full_info)

        with open(output_jsonl, mode=('a' if os.path.exists(output_jsonl) else 'w'), encoding='utf-8') as f:
            f.write(json.dumps(full_info) + "\n")
        
        time.sleep(random.uniform(1, 2))

    print("\n" + "="*50)
    print(f"Finished: {len(results)} papers info fetched")
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()